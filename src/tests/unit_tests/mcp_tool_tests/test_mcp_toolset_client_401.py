"""Tests for 401 detection in _MCPToolsetClient, including ExceptionGroup wrapping."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.mcp_tooling._mcp_session_manager import _MCPSessionManager
from quickapp.mcp_tooling._mcp_toolset_client import (
    _extract_http_401,
    _MCPToolsetClient,
    extract_external_service_signin_scope,
)
from quickapp.mcp_tooling._mcp_unauthorized_exception import MCPUnauthorizedException
from tests.unit_tests.common.common import noop_timeout_resolver


def _make_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    return httpx.HTTPStatusError("error", request=MagicMock(), response=response)


# --- _extract_http_401 unit tests ---


def test_extract_http_401_bare():
    err = _make_http_status_error(401)
    eg = ExceptionGroup("test", [err])
    assert _extract_http_401(eg) is err


def test_extract_http_401_nested():
    err = _make_http_status_error(401)
    inner = ExceptionGroup("inner", [err])
    outer = ExceptionGroup("outer", [RuntimeError("other"), inner])
    assert _extract_http_401(outer) is err


def test_extract_http_401_non_401():
    err = _make_http_status_error(500)
    eg = ExceptionGroup("test", [err])
    assert _extract_http_401(eg) is None


def test_extract_http_401_no_http_errors():
    eg = ExceptionGroup("test", [RuntimeError("unrelated")])
    assert _extract_http_401(eg) is None


def test_extract_http_401_mixed():
    err_401 = _make_http_status_error(401)
    err_500 = _make_http_status_error(500)
    eg = ExceptionGroup("test", [err_500, RuntimeError("x"), err_401])
    assert _extract_http_401(eg) is err_401


# --- extract_external_service_signin_scope unit tests ---

_CHALLENGE_SCOPE = "applications/my-app/external_services/salesforce"
_CHALLENGE_META = {
    "dial.epam.com/error": {"status_code": 401, "external_service": "salesforce"},
    "dial.epam.com/auth-challenge": [
        {"method": "external-service/signin", "scope": _CHALLENGE_SCOPE}
    ],
}


def test_extract_external_service_signin_scope_found():
    result = SimpleNamespace(isError=True, meta=_CHALLENGE_META)
    assert extract_external_service_signin_scope(result) == _CHALLENGE_SCOPE


def test_extract_external_service_signin_scope_not_error_ignored():
    """A challenge present but isError=False must be ignored (defensive; shouldn't happen)."""
    result = SimpleNamespace(isError=False, meta=_CHALLENGE_META)
    assert extract_external_service_signin_scope(result) is None


def test_extract_external_service_signin_scope_no_meta():
    result = SimpleNamespace(isError=True, meta=None)
    assert extract_external_service_signin_scope(result) is None


def test_extract_external_service_signin_scope_no_auth_challenge_key():
    result = SimpleNamespace(
        isError=True,
        meta={"dial.epam.com/error": {"status_code": 404, "external_service": "salesforce"}},
    )
    assert extract_external_service_signin_scope(result) is None


def test_extract_external_service_signin_scope_wrong_method():
    result = SimpleNamespace(
        isError=True,
        meta={"dial.epam.com/auth-challenge": [{"method": "toolset/signin", "scope": "x"}]},
    )
    assert extract_external_service_signin_scope(result) is None


def test_extract_external_service_signin_scope_not_a_list():
    result = SimpleNamespace(isError=True, meta={"dial.epam.com/auth-challenge": "not-a-list"})
    assert extract_external_service_signin_scope(result) is None


# --- _MCPToolsetClient integration tests ---

_STREAMABLE_HTTP_PATCH = "quickapp.mcp_tooling._mcp_toolset_client.streamable_http_client"
_SSE_PATCH = "quickapp.mcp_tooling._mcp_toolset_client.sse_client"


def _make_toolset_client(
    protocol: MCPProtocol = MCPProtocol.streamable_http,
) -> _MCPToolsetClient:
    toolset = MCPToolSet(
        mcp_server_info=MCPServerInfo(
            url="https://test-mcp", authorization=None, protocol=protocol
        ),
        name="test-toolset",
    )
    return _MCPToolsetClient(
        toolset_info=toolset,
        toolset_key="mcp:test-toolset",
        oauth_token_fetcher=MagicMock(),
        dial_settings=MagicMock(url="https://dial-core"),
        timeout_resolver=noop_timeout_resolver(),
        session_manager=_MCPSessionManager(RequestAsyncCloseRegistry()),
    )


@pytest.mark.asyncio
async def test_get_tools_list_bare_401_raises_unauthorized():
    cm = _make_toolset_client()
    err = _make_http_status_error(401)
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=err):
        with pytest.raises(MCPUnauthorizedException) as exc_info:
            await cm.get_tools_list()
        assert exc_info.value.toolset_name == "test-toolset"
        assert exc_info.value.__cause__ is err


@pytest.mark.asyncio
async def test_get_tools_list_exception_group_401_raises_unauthorized():
    """Streamable HTTP transport wraps 401 in ExceptionGroup — must still detect it."""
    cm = _make_toolset_client()
    err = _make_http_status_error(401)
    eg = ExceptionGroup("unhandled errors in a TaskGroup", [err])
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=eg):
        with pytest.raises(MCPUnauthorizedException) as exc_info:
            await cm.get_tools_list()
        assert exc_info.value.toolset_name == "test-toolset"
        assert exc_info.value.__cause__ is err


@pytest.mark.asyncio
async def test_get_tools_list_exception_group_non_401_propagates():
    cm = _make_toolset_client()
    err = _make_http_status_error(500)
    eg = ExceptionGroup("unhandled errors in a TaskGroup", [err])
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=eg):
        with pytest.raises(ExceptionGroup):
            await cm.get_tools_list()


@pytest.mark.asyncio
async def test_get_tools_list_bare_500_propagates():
    cm = _make_toolset_client()
    err = _make_http_status_error(500)
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=err):
        with pytest.raises(httpx.HTTPStatusError):
            await cm.get_tools_list()


@pytest.mark.asyncio
async def test_call_mcp_tool_exception_group_401_raises_unauthorized():
    cm = _make_toolset_client()
    err = _make_http_status_error(401)
    eg = ExceptionGroup("unhandled errors in a TaskGroup", [err])
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=eg):
        with pytest.raises(MCPUnauthorizedException):
            await cm.call_mcp_tool("some_tool", arg="val")


@pytest.mark.asyncio
async def test_call_mcp_tool_bare_401_raises_unauthorized():
    cm = _make_toolset_client()
    err = _make_http_status_error(401)
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=err):
        with pytest.raises(MCPUnauthorizedException):
            await cm.call_mcp_tool("some_tool")


@pytest.mark.asyncio
async def test_call_mcp_tool_bare_500_wraps_in_runtime_error():
    """Non-401 errors from call_mcp_tool get RuntimeError wrapping (preserving tool name context)."""
    cm = _make_toolset_client()
    err = _make_http_status_error(500)
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=err):
        with pytest.raises(RuntimeError, match="Error calling MCP tool"):
            await cm.call_mcp_tool("some_tool")


@pytest.mark.asyncio
async def test_sse_transport_401_raises_unauthorized():
    cm = _make_toolset_client(protocol=MCPProtocol.sse)
    err = _make_http_status_error(401)
    with patch(_SSE_PATCH, side_effect=err):
        with pytest.raises(MCPUnauthorizedException):
            await cm.get_tools_list()
