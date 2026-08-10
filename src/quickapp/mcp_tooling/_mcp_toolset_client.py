import functools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from injector import inject
from mcp import ClientSession, Tool
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from mcp.types import (
    BlobResourceContents,
    CallToolResult,
    InitializeResult,
    Resource,
    TextResourceContents,
)
from pydantic import AnyUrl as _AnyUrl

from quickapp.common import DIAL_BEARER, ForwardedHeaders
from quickapp.common.dial_settings import DialSettings
from quickapp.common.oauth_token_fetcher import OAuthTokenFetcher
from quickapp.common.tool_timeout_utils import MCP_TIMEOUT_CODE
from quickapp.config.toolsets.authorization import (
    BasicAuthorization,
    BearerAuthorization,
    ClientIdSecretAuthorization,
    MCPApiKeyAuthorization,
)
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.mcp_tooling._mcp_session_manager import _MCPSessionManager
from quickapp.mcp_tooling._mcp_unauthorized_exception import MCPUnauthorizedException
from quickapp.shared.config_resolvers.tool_timeout_resolver import ToolTimeoutResolver

MAX_ITERATIONS = 1000

# HTTP connect/write timeout for streamable HTTP; the SSE read timeout is resolved separately.
_MCP_HTTP_TIMEOUT_SECONDS = 30.0


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
class _MCPToolsetClient:
    """Per-toolset MCP client: auth headers + tool operations.

    Builds the toolset's authorization headers and runs its tool operations
    (``get_tools_list`` / ``call_mcp_tool`` / ``read_mcp_resource``), borrowing a
    shared, request-scoped session from :class:`_MCPSessionManager` rather than
    opening one per call.
    """

    def __init__(
        self,
        toolset_info: MCPToolSet,
        toolset_key: str,
        oauth_token_fetcher: OAuthTokenFetcher,
        dial_settings: DialSettings,
        timeout_resolver: ToolTimeoutResolver,
        session_manager: _MCPSessionManager,
        bearer: DIAL_BEARER = None,
        forwarded_headers: ForwardedHeaders = None,
    ):
        self.__toolset_info = toolset_info
        self.__toolset_key = toolset_key
        self.__oauth_token_fetcher: OAuthTokenFetcher = oauth_token_fetcher
        self.__dial_settings: DialSettings = dial_settings
        self.__bearer: DIAL_BEARER = bearer
        self.__forwarded_headers: ForwardedHeaders = forwarded_headers
        self.__timeout_resolver: ToolTimeoutResolver = timeout_resolver
        self.__session_manager: _MCPSessionManager = session_manager

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
    async def __open_transport_session(
        self, sse_read_timeout: float
    ) -> AsyncIterator[tuple[ClientSession, InitializeResult]]:
        """Internal transport setup — yields (session, InitializeResult).

        Both ``__open_session`` (for the session manager) and ``open_init_session``
        (for the initializer) delegate here to avoid duplication.
        """
        try:
            headers = await self.__build_headers(self.__toolset_info.mcp_server_info)

            if self.__toolset_info.mcp_server_info.protocol == MCPProtocol.streamable_http:
                http_client = httpx.AsyncClient(
                    headers=headers,
                    timeout=httpx.Timeout(_MCP_HTTP_TIMEOUT_SECONDS, read=sse_read_timeout),
                    follow_redirects=True,
                )
                async with http_client:
                    async with streamable_http_client(
                        self.__toolset_info.mcp_server_info.url,
                        http_client=http_client,
                    ) as (read_stream, write_stream, _):
                        async with ClientSession(read_stream, write_stream) as session:
                            init_result = await session.initialize()
                            yield session, init_result
            elif self.__toolset_info.mcp_server_info.protocol == MCPProtocol.sse:
                async with sse_client(
                    self.__toolset_info.mcp_server_info.url,
                    headers=headers,
                    sse_read_timeout=sse_read_timeout,
                ) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        init_result = await session.initialize()
                        yield session, init_result
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

    @asynccontextmanager
    async def __open_session(self, sse_read_timeout: float) -> AsyncIterator[ClientSession]:
        """Yields a ClientSession — thin wrapper for use by the session manager."""
        async with self.__open_transport_session(sse_read_timeout) as (session, _):
            yield session

    @asynccontextmanager
    async def open_init_session(self) -> AsyncIterator[tuple[ClientSession, InitializeResult]]:
        """Yields (session, InitializeResult) for the initializer.

        Used by ``_MCPToolInitializer._process_toolset`` to load tools and resources
        in one connection, capturing server capabilities from ``InitializeResult``.
        """
        async with self.__open_transport_session(self.__timeout_resolver.resolve()) as pair:
            yield pair

    @staticmethod
    async def get_tools_list(session: ClientSession) -> list[Tool]:
        """Return the tool list from the MCP server using the provided session."""
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

    @staticmethod
    async def get_resources_list(session: ClientSession) -> list[Resource]:
        """Return the full resource list from the server using the provided session."""
        current_cursor: str | None = None
        all_resources: list[Resource] = []

        iterations = 0

        while True:
            iterations += 1
            if iterations > MAX_ITERATIONS:
                msg = "Reached max of 1000 iterations while listing resources."
                raise RuntimeError(msg)

            result = await session.list_resources(cursor=current_cursor)

            if result.resources:
                all_resources.extend(result.resources)

            if not result.nextCursor:
                break

            current_cursor = result.nextCursor
        return all_resources

    @staticmethod
    async def read_resource_contents(
            session: ClientSession, uri: str
    ) -> list[TextResourceContents | BlobResourceContents]:
        """Read resource content using the provided init session (used at init time)."""
        result = await session.read_resource(_AnyUrl(uri))
        return result.contents

    async def read_mcp_resource(
        self, uri: str
    ) -> list[TextResourceContents | BlobResourceContents]:
        """Read resource content on-demand, reusing the long-lived request session."""
        timeout = self.__timeout_resolver.resolve()
        session = await self.__session_manager.get_session(
            self.__toolset_key, functools.partial(self.__open_session, timeout)
        )
        result = await session.read_resource(_AnyUrl(uri))
        return result.contents

    async def call_mcp_tool(self, tool_name: str, **kwargs) -> CallToolResult:
        timeout = self.__timeout_resolver.resolve()
        read_timeout_seconds = timedelta(seconds=timeout)

        try:
            # Borrow the request-scoped session: opened once per toolset, reused across
            # orchestrator iterations and concurrent calls, torn down at request end.
            session = await self.__session_manager.get_session(
                self.__toolset_key, functools.partial(self.__open_session, timeout)
            )
            return await session.call_tool(
                tool_name, kwargs, read_timeout_seconds=read_timeout_seconds
            )
        except MCPUnauthorizedException:
            raise
        except McpError as e:
            if getattr(e.error, "code", None) == MCP_TIMEOUT_CODE:
                raise
            raise RuntimeError(f"Error calling MCP tool '{tool_name}': {e}") from e
        except Exception as e:
            raise RuntimeError(f"Error calling MCP tool '{tool_name}': {e}") from e
