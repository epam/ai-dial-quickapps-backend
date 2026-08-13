import logging
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan, _current_http_request
from injector import inject

logger = logging.getLogger(__name__)


def _get_api_key_from_context() -> str:
    request = _current_http_request.get(None)
    if request is None:
        return ""
    return request.headers.get("api-key", request.headers.get("x-api-key", ""))


async def _call_quickapp(app: FastAPI, query: str, api_key: str) -> str:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/openai/deployments/quick_apps2/chat/completions",
            json={
                "messages": [{"role": "user", "content": query}],
                "stream": False,
            },
            headers={"api-key": api_key},
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if content is None:
            return ""
        return str(content)


@inject
class _McpEndpointService(AbstractAsyncContextManager):  # type: ignore[type-arg]
    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._fastmcp: FastMCP = FastMCP("QuickApp")
        self._mcp_starlette_app: StarletteWithLifespan | None = None
        self._lifespan_ctx: AbstractAsyncContextManager[Any] | None = None

        @self._fastmcp.tool()
        async def run(query: str) -> str:
            """Run the QuickApp agent with a user query and return the response."""
            api_key = _get_api_key_from_context()
            return await _call_quickapp(self._app, query, api_key)

    def build_starlette_app(self) -> StarletteWithLifespan:
        if self._mcp_starlette_app is None:
            self._mcp_starlette_app = self._fastmcp.http_app(
                path="/",
                stateless_http=True,
            )
        return self._mcp_starlette_app

    async def __aenter__(self) -> "_McpEndpointService":
        starlette_app = self.build_starlette_app()
        self._lifespan_ctx = starlette_app.lifespan(starlette_app)
        await self._lifespan_ctx.__aenter__()
        logger.info("MCP endpoint started")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # type: ignore[override]
        if self._lifespan_ctx is not None:
            result = await self._lifespan_ctx.__aexit__(exc_type, exc_val, exc_tb)
            self._lifespan_ctx = None
            logger.info("MCP endpoint stopped")
            return result
        return None
