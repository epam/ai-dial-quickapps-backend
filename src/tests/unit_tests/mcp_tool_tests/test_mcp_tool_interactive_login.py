"""Tests for interactive login retry in _MCPTool._run_in_stage_async."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common import CompletionResult
from quickapp.dial_core_services._login_result import LoginResult
from quickapp.mcp_tooling._mcp_tool import _MCPTool
from quickapp.mcp_tooling._mcp_unauthorized_exception import MCPUnauthorizedException
from tests.unit_tests.common.common import noop_timeout_resolver


def _make_mcp_tool(
    *,
    dial_toolset_id: str | None = "toolsets/public/ts1",
    login_result: LoginResult = LoginResult.SUCCESS,
) -> tuple[_MCPTool, AsyncMock, AsyncMock]:
    """Create an _MCPTool with mocked dependencies. Returns (tool, connection_manager, login_service)."""
    tool_meta = SimpleNamespace(
        name="test_tool",
        description="test",
        inputSchema={"type": "object", "properties": {}},
    )
    tool_config = MagicMock()
    tool_config.attachment.supported_types = []

    connection_manager = AsyncMock()
    login_service = AsyncMock()
    login_service.request_signin = AsyncMock(return_value=login_result)

    mcp_tool = _MCPTool(
        tool=tool_meta,
        tool_config=tool_config,
        connection_manager=connection_manager,
        stage_wrapper_builder=MagicMock(),
        state_holder=MagicMock(),
        dial_attachment_service=MagicMock(),
        perf_timer=MagicMock(),
        file_service=MagicMock(),
        dial_toolset_id=dial_toolset_id,
        login_service=login_service,
        timeout_resolver=noop_timeout_resolver(),
    )
    return mcp_tool, connection_manager, login_service


def _ok_result():
    return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], isError=False)


@pytest.mark.asyncio
async def test_successful_call_no_login():
    """Normal tool call — no 401, no interactive login."""
    tool, conn, login = _make_mcp_tool()
    conn.call_mcp_tool.return_value = _ok_result()

    result = await tool._run_in_stage_async(None)

    assert isinstance(result, CompletionResult)
    assert result.content == "ok"
    login.request_signin.assert_not_awaited()
    conn.call_mcp_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_401_triggers_login_and_retry():
    """401 on first call → login → retry succeeds."""
    tool, conn, login = _make_mcp_tool(login_result=LoginResult.SUCCESS)
    conn.call_mcp_tool.side_effect = [MCPUnauthorizedException("ts1"), _ok_result()]

    result = await tool._run_in_stage_async(None)

    assert result.content == "ok"
    login.request_signin.assert_awaited_once_with("toolsets/public/ts1")
    assert conn.call_mcp_tool.await_count == 2


@pytest.mark.asyncio
async def test_401_login_denied_raises():
    """401 → login returns DENIED → exception propagates."""
    tool, conn, login = _make_mcp_tool(login_result=LoginResult.DENIED)
    conn.call_mcp_tool.side_effect = MCPUnauthorizedException("ts1")

    with pytest.raises(MCPUnauthorizedException):
        await tool._run_in_stage_async(None)

    login.request_signin.assert_awaited_once()
    conn.call_mcp_tool.assert_awaited_once()  # no retry


@pytest.mark.asyncio
async def test_401_no_dial_toolset_id_raises():
    """401 with no dial_toolset_id → exception propagates without login attempt."""
    tool, conn, login = _make_mcp_tool(dial_toolset_id=None)
    conn.call_mcp_tool.side_effect = MCPUnauthorizedException("ts1")

    with pytest.raises(MCPUnauthorizedException):
        await tool._run_in_stage_async(None)

    login.request_signin.assert_not_awaited()


@pytest.mark.asyncio
async def test_401_on_retry_propagates():
    """401 on first call → login succeeds → 401 on retry → propagates."""
    tool, conn, login = _make_mcp_tool(login_result=LoginResult.SUCCESS)
    conn.call_mcp_tool.side_effect = [
        MCPUnauthorizedException("ts1"),
        MCPUnauthorizedException("ts1"),
    ]

    with pytest.raises(MCPUnauthorizedException):
        await tool._run_in_stage_async(None)

    assert conn.call_mcp_tool.await_count == 2
    login.request_signin.assert_awaited_once()


@pytest.mark.asyncio
async def test_401_no_channel_raises():
    """401 → login returns NO_CHANNEL → exception propagates."""
    tool, conn, login = _make_mcp_tool(login_result=LoginResult.NO_CHANNEL)
    conn.call_mcp_tool.side_effect = MCPUnauthorizedException("ts1")

    with pytest.raises(MCPUnauthorizedException):
        await tool._run_in_stage_async(None)
