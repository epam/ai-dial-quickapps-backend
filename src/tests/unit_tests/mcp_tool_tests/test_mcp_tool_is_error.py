"""Tests for MCPToolErrorException raised when MCP tool returns isError=True."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common import ToolCallResult
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.tool_fallback import (
    ContinueStrategyModel,
    ToolFallbackConfig,
    TriggerOn,
    TriggerOnType,
)
from quickapp.mcp_tooling._mcp_tool import _MCPTool
from quickapp.mcp_tooling._mcp_tool_error_exception import MCPToolErrorException
from tests.unit_tests.common.common import noop_timeout_resolver

_TOOL_META = SimpleNamespace(
    name="test_tool",
    description="test",
    inputSchema={"type": "object", "properties": {}},
)


def _make_mcp_tool(
    fallback_config: ToolFallbackConfig | None = None,
) -> tuple[_MCPTool, AsyncMock]:
    """Create an _MCPTool with mocked dependencies. Returns (tool, connection_manager)."""
    tool_config = MagicMock()
    tool_config.attachment.supported_types = []
    tool_config.display = None
    tool_config.fallback_configuration = fallback_config or ToolFallbackConfig()

    connection_manager = AsyncMock()

    mcp_tool = _MCPTool(
        tool=_TOOL_META,
        tool_config=tool_config,
        connection_manager=connection_manager,
        stage_wrapper_builder=MagicMock(),
        state_holder=MagicMock(),
        dial_attachment_service=MagicMock(),
        perf_timer=MagicMock(),
        file_service=MagicMock(),
        dial_toolset_id=None,
        login_service=MagicMock(),
        timeout_resolver=noop_timeout_resolver(),
        stage_display_level=StageDisplayLevel.INFO,
    )
    return mcp_tool, connection_manager


@pytest.mark.asyncio
async def test_is_error_raises_mcp_tool_error_exception():
    """isError=True raises MCPToolErrorException carrying the error text from content."""
    tool, conn = _make_mcp_tool()
    conn.call_mcp_tool.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Something went wrong")],
        isError=True,
    )

    with pytest.raises(MCPToolErrorException) as exc_info:
        await tool._run_in_stage_async(None)

    assert exc_info.value.tool_name == "test_tool"
    assert exc_info.value.error_message == "Something went wrong"


@pytest.mark.asyncio
async def test_is_error_with_multiple_text_blocks_joins_all():
    """isError=True with multiple text blocks joins them all into the error message."""
    tool, conn = _make_mcp_tool()
    conn.call_mcp_tool.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Error part 1"),
            SimpleNamespace(type="text", text="Error part 2"),
        ],
        isError=True,
    )

    with pytest.raises(MCPToolErrorException) as exc_info:
        await tool._run_in_stage_async(None)

    assert exc_info.value.error_message == "Error part 1\n\nError part 2"


@pytest.mark.asyncio
async def test_is_error_with_empty_content_raises_with_empty_message():
    """isError=True with no content raises MCPToolErrorException with an empty error message."""
    tool, conn = _make_mcp_tool()
    conn.call_mcp_tool.return_value = SimpleNamespace(
        content=[],
        isError=True,
    )

    with pytest.raises(MCPToolErrorException) as exc_info:
        await tool._run_in_stage_async(None)

    assert exc_info.value.tool_name == "test_tool"
    assert exc_info.value.error_message == ""


@pytest.mark.asyncio
async def test_is_error_false_returns_result_normally():
    """isError=False returns a ToolCallResult — regression guard."""
    tool, conn = _make_mcp_tool()
    conn.call_mcp_tool.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="success")],
        isError=False,
    )

    result = await tool._run_in_stage_async(None)

    assert isinstance(result, ToolCallResult)
    assert result.content == "success"


# ---------------------------------------------------------------------------
# Fallback strategy integration — tested via arun() to cover the full path
# in staged_base_tool.__run_tool_body.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_error_applies_continue_fallback_strategy():
    """isError=True → MCPToolErrorException → catch-all ContinueStrategy returns its instructions."""
    fallback_config = ToolFallbackConfig(
        strategies=[ContinueStrategyModel(instructions="Use your own knowledge instead.")]
    )
    tool, conn = _make_mcp_tool(fallback_config)
    conn.call_mcp_tool.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Internal server error")],
        isError=True,
    )

    result = await tool.arun("call-id")

    assert isinstance(result, ToolCallResult)
    assert result.tool_call_id == "call-id"
    assert result.content == "Use your own knowledge instead."


@pytest.mark.asyncio
async def test_is_error_applies_strategy_matching_error_text():
    """isError=True with trigger_on that matches the error text applies the strategy."""
    fallback_config = ToolFallbackConfig(
        strategies=[
            ContinueStrategyModel(
                trigger_on=TriggerOn(type=TriggerOnType.contains, value="rate limit"),
                instructions="Rate limited — try again later.",
            )
        ]
    )
    tool, conn = _make_mcp_tool(fallback_config)
    conn.call_mcp_tool.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Rate limit exceeded")],
        isError=True,
    )

    result = await tool.arun("call-id")

    assert result.content == "Rate limited — try again later."


@pytest.mark.asyncio
async def test_is_error_propagates_when_no_strategy_matches():
    """isError=True when trigger_on doesn't match → MCPToolErrorException propagates."""
    fallback_config = ToolFallbackConfig(
        strategies=[
            ContinueStrategyModel(
                trigger_on=TriggerOn(type=TriggerOnType.contains, value="rate limit"),
                instructions="Rate limited — try again later.",
            )
        ]
    )
    tool, conn = _make_mcp_tool(fallback_config)
    conn.call_mcp_tool.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Internal server error")],
        isError=True,
    )

    with pytest.raises(MCPToolErrorException):
        await tool.arun("call-id")
