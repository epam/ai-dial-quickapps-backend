"""Tests for 401 detection in _MCPToolsetClient, including ExceptionGroup wrapping."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest

from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.mcp_tooling._mcp_session_manager import _MCPSessionManager
from quickapp.mcp_tooling._mcp_toolset_client import _extract_http_401, _MCPToolsetClient
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
async def test_open_init_session_bare_401_raises_unauthorized():
    cm = _make_toolset_client()
    err = _make_http_status_error(401)
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=err):
        with pytest.raises(MCPUnauthorizedException) as exc_info:
            async with cm.open_init_session():
                pass
        assert exc_info.value.toolset_name == "test-toolset"
        assert exc_info.value.__cause__ is err


@pytest.mark.asyncio
async def test_open_init_session_exception_group_401_raises_unauthorized():
    """Streamable HTTP transport wraps 401 in ExceptionGroup — must still detect it."""
    cm = _make_toolset_client()
    err = _make_http_status_error(401)
    eg = ExceptionGroup("unhandled errors in a TaskGroup", [err])
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=eg):
        with pytest.raises(MCPUnauthorizedException) as exc_info:
            async with cm.open_init_session():
                pass
        assert exc_info.value.toolset_name == "test-toolset"
        assert exc_info.value.__cause__ is err


@pytest.mark.asyncio
async def test_open_init_session_exception_group_non_401_propagates():
    cm = _make_toolset_client()
    err = _make_http_status_error(500)
    eg = ExceptionGroup("unhandled errors in a TaskGroup", [err])
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=eg):
        with pytest.raises(ExceptionGroup):
            async with cm.open_init_session():
                pass


@pytest.mark.asyncio
async def test_open_init_session_bare_500_propagates():
    cm = _make_toolset_client()
    err = _make_http_status_error(500)
    with patch(_STREAMABLE_HTTP_PATCH, side_effect=err):
        with pytest.raises(httpx.HTTPStatusError):
            async with cm.open_init_session():
                pass


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
            async with cm.open_init_session():
                pass


async def _call_on_live_session_that_dies(cm: _MCPToolsetClient, status_code: int):
    """Open a session, then kill its owner with an HTTP error while a call is in flight."""
    session = MagicMock()

    @asynccontextmanager
    async def fake_open(_timeout: float):
        try:
            yield session
        finally:
            raise ExceptionGroup(
                "unhandled errors in a TaskGroup", [_make_http_status_error(status_code)]
            )

    async def hang(*_args, **_kwargs):
        await asyncio.Event().wait()

    session.call_tool = hang
    cm._MCPToolsetClient__open_session = fake_open  # type: ignore[attr-defined]

    call_task = asyncio.create_task(cm.call_mcp_tool("some_tool"))
    await asyncio.sleep(0.05)
    await cm._MCPToolsetClient__session_manager.aclose_all()  # type: ignore[attr-defined]
    return await call_task


@pytest.mark.asyncio
async def test_call_mcp_tool_403_on_live_session_fails_fast():
    """HTTP 403 kills the session owner and must not leave the tool call hung until timeout."""
    cm = _make_toolset_client()
    with pytest.raises(RuntimeError, match=r"HTTP 403") as exc_info:
        await asyncio.wait_for(_call_on_live_session_that_dies(cm, 403), timeout=2)
    assert "://" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_call_mcp_tool_401_on_live_session_stays_unauthorized():
    """A 401 that arrives as the owner dying must still be MCPUnauthorizedException."""
    cm = _make_toolset_client()
    with pytest.raises(MCPUnauthorizedException):
        await asyncio.wait_for(_call_on_live_session_that_dies(cm, 401), timeout=2)
