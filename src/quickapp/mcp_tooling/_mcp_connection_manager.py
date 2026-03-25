from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from injector import inject
from mcp import ClientSession, Tool
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult

from quickapp.common import DIAL_BEARER, ForwardedHeaders
from quickapp.common.dial_settings import DialSettings
from quickapp.common.oauth_token_fetcher import OAuthTokenFetcher
from quickapp.config.toolsets.authorization import (
    BasicAuthorization,
    BearerAuthorization,
    ClientIdSecretAuthorization,
    MCPApiKeyAuthorization,
)
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.mcp_tooling._mcp_unauthorized_exception import MCPUnauthorizedException

MAX_ITERATIONS = 1000


def _extract_http_401(eg: BaseExceptionGroup) -> httpx.HTTPStatusError | None:
    """Extract an httpx.HTTPStatusError with status 401 from an ExceptionGroup, if present."""
    for exc in eg.exceptions:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 401:
            return exc
        if isinstance(exc, BaseExceptionGroup):
            nested = _extract_http_401(exc)
            if nested is not None:
                return nested
    return None


@inject
class _MCPConnectionManager:
    """Manages MCP connections and sessions."""

    def __init__(
        self,
        toolset_info: MCPToolSet,
        oauth_token_fetcher: OAuthTokenFetcher,
        dial_settings: DialSettings,
        bearer: DIAL_BEARER = None,
        forwarded_headers: ForwardedHeaders = None,
    ):
        self.__toolset_info = toolset_info
        self.__oauth_token_fetcher: OAuthTokenFetcher = oauth_token_fetcher
        self.__dial_settings: DialSettings = dial_settings
        self.__bearer: DIAL_BEARER = bearer
        self.__forwarded_headers: ForwardedHeaders = forwarded_headers

    async def __build_headers(self, server_info: MCPServerInfo) -> dict:
        headers = (
            {"Authorization": f"Bearer {self.__bearer.get_secret_value()}"}
            if (
                self.__bearer
                and self.__toolset_info.mcp_server_info.url.startswith(
                    self.__dial_settings.url
                )  # append header only for Dial-internal servers
            )
            else {}
        )
        match server_info.authorization:
            case BasicAuthorization(username=username, password=password):
                import base64

                credentials = f"{username}:{password}"
                encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
                headers["Authorization"] = f"Basic {encoded_credentials}"
            case BearerAuthorization(token=token):
                headers["Authorization"] = f"Bearer {token}"
            case MCPApiKeyAuthorization(name=name, key=key):
                headers[name] = key
            case ClientIdSecretAuthorization() as auth:
                token = await self.__oauth_token_fetcher.fetch_oauth_token(auth)
                headers["Authorization"] = f"Bearer {token}"
        if self.__forwarded_headers:
            headers.update(self.__forwarded_headers)
        return headers

    @asynccontextmanager
    async def __session_context(self) -> AsyncIterator[ClientSession]:
        """
        Async context manager that yields an initialized ClientSession for the given server_info.
        Automatically builds headers, opens the underlying connection (SSE or streamable HTTP),
        initializes the session, and ensures clean teardown.

        Raises MCPUnauthorizedException if the MCP server returns HTTP 401.
        """
        try:
            headers = await self.__build_headers(self.__toolset_info.mcp_server_info)

            if self.__toolset_info.mcp_server_info.protocol == MCPProtocol.streamable_http:
                async with streamablehttp_client(
                    self.__toolset_info.mcp_server_info.url, headers=headers
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        yield session
            elif self.__toolset_info.mcp_server_info.protocol == MCPProtocol.sse:
                async with sse_client(self.__toolset_info.mcp_server_info.url, headers=headers) as (
                    read_stream,
                    write_stream,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        yield session
            else:
                raise ValueError(
                    f"Unsupported protocol: {self.__toolset_info.mcp_server_info.protocol}"
                )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise MCPUnauthorizedException(toolset_name=self.__toolset_info.name) from e
            raise
        except BaseExceptionGroup as eg:
            http_401 = _extract_http_401(eg)
            if http_401 is not None:
                raise MCPUnauthorizedException(toolset_name=self.__toolset_info.name) from http_401
            raise

    async def get_tools_list(self) -> list[Tool]:
        """Return the tool list from the MCP server."""
        async with self.__session_context() as session:
            current_cursor: str | None = None
            all_tools: list[Tool] = []

            iterations = 0

            while True:
                iterations += 1
                if iterations > MAX_ITERATIONS:
                    msg = "Reached max of 1000 iterations while listing tools."
                    raise RuntimeError(msg)

                list_tools_page_result = await session.list_tools(cursor=current_cursor)

                if list_tools_page_result.tools:
                    all_tools.extend(list_tools_page_result.tools)

                # Pagination spec: https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination
                # compatible with None or ""
                if not list_tools_page_result.nextCursor:
                    break

                current_cursor = list_tools_page_result.nextCursor
            return all_tools

    async def call_mcp_tool(self, tool_name: str, **kwargs) -> CallToolResult:
        try:
            async with self.__session_context() as session:
                if kwargs is None:
                    return await session.call_tool(tool_name)
                return await session.call_tool(tool_name, kwargs)
        except MCPUnauthorizedException:
            raise
        except Exception as e:
            raise RuntimeError(f"Error calling MCP tool '{tool_name}': {e}") from e
