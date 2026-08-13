import logging

from fastapi import FastAPI
from injector import inject

from quickapp.common.base_initializer import StartupInitializer

from ._mcp_endpoint_service import _McpEndpointService

logger = logging.getLogger(__name__)


@inject
class _McpRouteInitializer(StartupInitializer):  # type: ignore[misc]
    def __init__(self, app: FastAPI, service: _McpEndpointService) -> None:
        self._app = app
        self._service = service

    async def initialize(self) -> None:
        starlette_app = self._service.build_starlette_app()
        self._app.mount("/mcp", starlette_app)
        logger.info("MCP endpoint mounted at /mcp")
