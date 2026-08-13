from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from quickapp.mcp_endpoint._mcp_endpoint_service import (
    _call_quickapp,
    _get_api_key_from_context,
    _McpEndpointService,
)


class TestGetApiKeyFromContext:

    def test_returns_empty_when_no_request_in_context(self):
        from fastmcp.server.http import _current_http_request

        token = _current_http_request.set(None)
        try:
            assert _get_api_key_from_context() == ""
        finally:
            _current_http_request.reset(token)

    def test_reads_api_key_header(self):
        from fastmcp.server.http import _current_http_request

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"api-key": "test-key-123"}
        token = _current_http_request.set(mock_request)
        try:
            assert _get_api_key_from_context() == "test-key-123"
        finally:
            _current_http_request.reset(token)

    def test_falls_back_to_x_api_key_header(self):
        from fastmcp.server.http import _current_http_request

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"x-api-key": "fallback-key"}
        token = _current_http_request.set(mock_request)
        try:
            assert _get_api_key_from_context() == "fallback-key"
        finally:
            _current_http_request.reset(token)

    def test_api_key_takes_precedence_over_x_api_key(self):
        from fastmcp.server.http import _current_http_request

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"api-key": "primary", "x-api-key": "secondary"}
        token = _current_http_request.set(mock_request)
        try:
            assert _get_api_key_from_context() == "primary"
        finally:
            _current_http_request.reset(token)


class TestCallQuickapp:

    @pytest.mark.asyncio
    async def test_returns_content_from_chat_completion_response(self):
        mock_app = MagicMock()
        expected_content = "Hello from QuickApp!"
        response_json = {
            "choices": [{"message": {"role": "assistant", "content": expected_content}}]
        }
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=response_json)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("quickapp.mcp_endpoint._mcp_endpoint_service.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = mock_client
            result = await _call_quickapp(mock_app, "What is 2+2?", "my-key")

        assert result == expected_content
        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.args[0] == "/openai/deployments/quick_apps2/chat/completions"
        body = call_kwargs.kwargs["json"]
        assert body["messages"] == [{"role": "user", "content": "What is 2+2?"}]
        assert body["stream"] is False
        assert call_kwargs.kwargs["headers"]["api-key"] == "my-key"

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_content_is_none(self):
        mock_app = MagicMock()
        response_json = {"choices": [{"message": {"role": "assistant", "content": None}}]}
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=response_json)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("quickapp.mcp_endpoint._mcp_endpoint_service.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = mock_client
            result = await _call_quickapp(mock_app, "query", "key")

        assert result == ""


class TestMcpRouteInitializer:

    @pytest.mark.asyncio
    async def test_initialize_mounts_mcp_route(self):
        from quickapp.mcp_endpoint._mcp_route_initializer import _McpRouteInitializer

        mock_app = MagicMock()
        mock_service = MagicMock(spec=_McpEndpointService)
        mock_starlette_app = MagicMock()
        mock_service.build_starlette_app.return_value = mock_starlette_app

        initializer = _McpRouteInitializer(app=mock_app, service=mock_service)
        await initializer.initialize()

        mock_service.build_starlette_app.assert_called_once()
        mock_app.mount.assert_called_once_with("/mcp", mock_starlette_app)


class TestMcpEndpointServiceLifespan:

    @pytest.mark.asyncio
    async def test_aenter_aexit_delegate_to_starlette_lifespan(self):
        mock_fastapi = MagicMock()
        service = _McpEndpointService(app=mock_fastapi)

        entered = []
        exited = []

        @asynccontextmanager
        async def fake_lifespan():
            entered.append(True)
            yield
            exited.append(True)

        mock_starlette = MagicMock()
        mock_starlette.lifespan = MagicMock(return_value=fake_lifespan())

        with patch.object(service, "build_starlette_app", return_value=mock_starlette):
            async with service:
                assert len(entered) == 1
                assert len(exited) == 0

        assert len(exited) == 1
