from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import BlobResourceContents, TextResourceContents
from pydantic import AnyUrl

from quickapp.common.exceptions import InvalidToolCallParameterException, ToolErrorException
from quickapp.config.application import StageDisplayLevel
from quickapp.mcp_tooling._mcp_resource_meta import MCPResourceMeta
from quickapp.mcp_tooling._mcp_tooling_context import _MCPToolingContext
from quickapp.mcp_tooling._mcp_unauthorized_exception import MCPUnauthorizedException
from quickapp.mcp_tooling._read_mcp_resource_tool import (
    READ_MCP_RESOURCE_TOOL_CONFIG,
    _ReadMcpResourceTool,
)


def _meta(uri: str, toolset: str = "ts", name: str = "res") -> MCPResourceMeta:
    return MCPResourceMeta(
        resource_name=name,
        resource_uri=uri,
        toolset_name=toolset,
        toolset_description=None,
    )


def _context(
    metas: list[MCPResourceMeta],
    clients: dict | None = None,
) -> _MCPToolingContext:
    ctx = _MCPToolingContext()
    ctx.extend_resource_metas(metas)
    for name, client in (clients or {}).items():
        ctx.register_client(name, client)
    return ctx


def _make_tool(context: _MCPToolingContext) -> _ReadMcpResourceTool:
    return _ReadMcpResourceTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=READ_MCP_RESOURCE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        context=context,
    )


def _text_content(text: str, uri: str = "urn://x") -> TextResourceContents:
    return TextResourceContents(uri=AnyUrl(uri), text=text, mimeType=None)


def _blob_content(uri: str = "urn://x") -> BlobResourceContents:
    return BlobResourceContents(uri=AnyUrl(uri), blob="abc123", mimeType=None)


# --- Missing/invalid args ---


@pytest.mark.asyncio
async def test_missing_uri_returns_error():
    tool = _make_tool(_context([]))
    with pytest.raises(InvalidToolCallParameterException) as excinfo:
        await tool._run_in_stage_async(uri=None)
    assert excinfo.value.parameter_name == "uri"


@pytest.mark.asyncio
async def test_empty_uri_returns_error():
    tool = _make_tool(_context([]))
    with pytest.raises(InvalidToolCallParameterException) as excinfo:
        await tool._run_in_stage_async(uri="")
    assert excinfo.value.parameter_name == "uri"


# --- Resource not found ---


@pytest.mark.asyncio
async def test_unknown_uri_returns_error():
    tool = _make_tool(_context([_meta("urn://known")]))
    with pytest.raises(InvalidToolCallParameterException) as excinfo:
        await tool._run_in_stage_async(uri="urn://unknown")
    assert "No resource registered" in excinfo.value.message
    assert "urn://unknown" in excinfo.value.message


@pytest.mark.asyncio
async def test_toolset_filter_no_match_returns_error():
    ctx = _context([_meta("urn://x", toolset="ts1")])
    tool = _make_tool(ctx)
    with pytest.raises(InvalidToolCallParameterException, match="No resource registered"):
        await tool._run_in_stage_async(uri="urn://x", toolset="ts_other")


# --- Ambiguity ---


@pytest.mark.asyncio
async def test_multiple_toolsets_same_uri_without_toolset_arg_returns_disambiguation_error():
    ctx = _context([_meta("urn://x", "ts1"), _meta("urn://x", "ts2")])
    tool = _make_tool(ctx)
    with pytest.raises(InvalidToolCallParameterException) as excinfo:
        await tool._run_in_stage_async(uri="urn://x")
    message = excinfo.value.message
    assert "Multiple toolsets" in message
    assert "ts1" in message
    assert "ts2" in message
    assert excinfo.value.parameter_name == "toolset"


@pytest.mark.asyncio
async def test_multiple_toolsets_same_uri_with_toolset_arg_resolves_correctly():
    client1 = MagicMock()
    client1.read_mcp_resource = AsyncMock(return_value=[_text_content("from ts1")])
    ctx = _context(
        [_meta("urn://x", "ts1"), _meta("urn://x", "ts2")],
        clients={"ts1": client1},
    )
    tool = _make_tool(ctx)
    result = await tool._run_in_stage_async(uri="urn://x", toolset="ts1")
    assert result.content == "from ts1"


# --- Client not registered ---


@pytest.mark.asyncio
async def test_no_client_for_toolset_returns_error():
    ctx = _context([_meta("urn://x", "ts")], clients={})
    tool = _make_tool(ctx)
    with pytest.raises(ToolErrorException) as excinfo:
        await tool._run_in_stage_async(uri="urn://x")
    assert "No client registered" in excinfo.value.error_message
    assert "ts" in excinfo.value.error_message


# --- Read failures ---


@pytest.mark.asyncio
async def test_client_read_exception_returns_error():
    client = MagicMock()
    client.read_mcp_resource = AsyncMock(side_effect=RuntimeError("network down"))
    ctx = _context([_meta("urn://x", "ts")], clients={"ts": client})
    tool = _make_tool(ctx)
    with pytest.raises(ToolErrorException) as excinfo:
        await tool._run_in_stage_async(uri="urn://x")
    assert "Error reading resource" in excinfo.value.error_message
    assert "network down" in excinfo.value.error_message


@pytest.mark.asyncio
async def test_unauthorized_exception_propagates_unwrapped():
    client = MagicMock()
    client.read_mcp_resource = AsyncMock(side_effect=MCPUnauthorizedException("ts"))
    ctx = _context([_meta("urn://x", "ts")], clients={"ts": client})
    tool = _make_tool(ctx)
    with pytest.raises(MCPUnauthorizedException):
        await tool._run_in_stage_async(uri="urn://x")


# --- Content handling ---


@pytest.mark.asyncio
async def test_text_content_returned():
    client = MagicMock()
    client.read_mcp_resource = AsyncMock(return_value=[_text_content("hello world")])
    ctx = _context([_meta("urn://x")], clients={"ts": client})
    tool = _make_tool(ctx)
    result = await tool._run_in_stage_async(uri="urn://x")
    assert result.content == "hello world"
    assert result.is_error is False


@pytest.mark.asyncio
async def test_blob_content_returns_unsupported_message():
    client = MagicMock()
    client.read_mcp_resource = AsyncMock(return_value=[_blob_content()])
    ctx = _context([_meta("urn://x")], clients={"ts": client})
    tool = _make_tool(ctx)
    result = await tool._run_in_stage_async(uri="urn://x")
    assert "binary content" in result.content.lower()
    assert "not supported" in result.content.lower()


@pytest.mark.asyncio
async def test_mixed_text_and_blob_combines_results():
    client = MagicMock()
    client.read_mcp_resource = AsyncMock(return_value=[_text_content("part one"), _blob_content()])
    ctx = _context([_meta("urn://x")], clients={"ts": client})
    tool = _make_tool(ctx)
    result = await tool._run_in_stage_async(uri="urn://x")
    assert "part one" in result.content
    assert "binary content" in result.content.lower()


@pytest.mark.asyncio
async def test_empty_content_list_returns_no_content_message():
    client = MagicMock()
    client.read_mcp_resource = AsyncMock(return_value=[])
    ctx = _context([_meta("urn://x")], clients={"ts": client})
    tool = _make_tool(ctx)
    result = await tool._run_in_stage_async(uri="urn://x")
    assert "no content" in result.content.lower()


@pytest.mark.asyncio
async def test_multiple_text_parts_joined_with_double_newline():
    client = MagicMock()
    client.read_mcp_resource = AsyncMock(
        return_value=[_text_content("first"), _text_content("second")]
    )
    ctx = _context([_meta("urn://x")], clients={"ts": client})
    tool = _make_tool(ctx)
    result = await tool._run_in_stage_async(uri="urn://x")
    assert result.content == "first\n\nsecond"


@pytest.mark.asyncio
async def test_stage_wrapper_receives_result_when_provided():
    client = MagicMock()
    client.read_mcp_resource = AsyncMock(return_value=[_text_content("data")])
    ctx = _context([_meta("urn://x")], clients={"ts": client})
    tool = _make_tool(ctx)

    stage_wrapper = MagicMock()
    result = await tool._run_in_stage_async(stage_wrapper=stage_wrapper, uri="urn://x")

    stage_wrapper.add_result.assert_called_once_with(result)


@pytest.mark.asyncio
async def test_failure_is_converted_to_error_result_by_the_base_tool():
    tool = _ReadMcpResourceTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=READ_MCP_RESOURCE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        context=_context([]),
        stage_display_level=StageDisplayLevel.NONE,
    )
    result = await tool.arun("call-1", uri="urn://unknown")
    assert result.is_error is True
    assert result.tool_call_id == "call-1"
    assert "urn://unknown" in result.content
