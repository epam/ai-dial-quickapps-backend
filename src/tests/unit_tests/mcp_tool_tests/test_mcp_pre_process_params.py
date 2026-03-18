import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.config.tools.mcp import MCPTool
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.file_transfer._file_argument_transformer import _FileArgumentTransformer
from quickapp.mcp_tooling._mcp_connection_manager import _MCPConnectionManager
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper
from quickapp.mcp_tooling._mcp_tool import _MCPTool


def _make_tool(
    input_schema: dict | None = None,
    dial_toolset_id: str | None = None,
) -> tuple[_MCPTool, MagicMock]:
    """Create an _MCPTool with mocked dependencies.

    Returns the tool and the mocked DialFileService for assertions.
    """
    tool = SimpleNamespace(
        name="test_tool",
        description="Test tool",
        inputSchema=input_schema or {},
    )
    tool_config = MagicMock(spec=MCPTool)
    tool_config.attachment = MagicMock()
    tool_config.attachment.supported_types = []
    connection_manager = MagicMock(spec=_MCPConnectionManager)
    stage_wrapper_builder = MagicMock()
    stage_wrapper_builder.build.return_value = MagicMock(spec=_MCPStageWrapper)
    state_holder = StateHolder()
    attachment_service = MagicMock(spec=AttachmentService)
    perf_timer = PerformanceTimer()
    file_service = MagicMock(spec=DialFileService)
    file_service.download_file = AsyncMock()
    file_service.grant_permissions_to_files = AsyncMock()

    file_transformer = _FileArgumentTransformer(file_service=file_service)

    mcp_tool = _MCPTool(
        tool=tool,
        tool_config=tool_config,
        connection_manager=connection_manager,
        stage_wrapper_builder=stage_wrapper_builder,
        state_holder=state_holder,
        dial_attachment_service=attachment_service,
        perf_timer=perf_timer,
        file_service=file_service,
        dial_toolset_id=dial_toolset_id,
        argument_transformers=[file_transformer],
    )
    return mcp_tool, file_service


class TestPreProcessParams:
    @pytest.mark.asyncio
    async def test_base64_prefix(self):
        tool, file_service = _make_tool()
        raw = b"binary data"
        file_service.download_file.return_value = raw

        result = await tool._pre_process_params(image="file:base64::files/photo.png")

        file_service.download_file.assert_awaited_once_with("files/photo.png")
        assert result["image"] == base64.b64encode(raw).decode()

    @pytest.mark.asyncio
    async def test_text_prefix(self):
        tool, file_service = _make_tool()
        file_service.download_file.return_value = b"decoded text"

        result = await tool._pre_process_params(content="file:text::files/doc.txt")

        file_service.download_file.assert_awaited_once_with("files/doc.txt")
        assert result["content"] == "decoded text"

    @pytest.mark.asyncio
    async def test_url_prefix_no_dial_url(self):
        tool, _ = _make_tool(input_schema={"properties": {"link": {"type": "string"}}})
        result = await tool._pre_process_params(link="file:url::https://example.com/data")
        assert result["link"] == "https://example.com/data"

    @pytest.mark.asyncio
    async def test_url_prefix_with_dial_url_true(self):
        tool, file_service = _make_tool(
            input_schema={"properties": {"doc_url": {"type": "string", "dial_url": True}}},
            dial_toolset_id="my-toolset",
        )
        result = await tool._pre_process_params(doc_url="file:url::files/report.pdf")
        assert result["doc_url"] == "files/report.pdf"
        file_service.grant_permissions_to_files.assert_awaited_once_with(
            ["files/report.pdf"], "my-toolset"
        )

    @pytest.mark.asyncio
    async def test_url_prefix_with_dial_url_false(self):
        tool, file_service = _make_tool(
            input_schema={"properties": {"doc_url": {"type": "string", "dial_url": False}}},
        )
        result = await tool._pre_process_params(doc_url="file:url::files/report.pdf")
        assert result["doc_url"] == "files/report.pdf"
        file_service.grant_permissions_to_files.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_prefix_raises_exception(self):
        tool, _ = _make_tool()
        with pytest.raises(InvalidToolCallParameterException, match="Missing required file prefix"):
            await tool._pre_process_params(param="file:files/some.txt")

    @pytest.mark.asyncio
    async def test_non_string_values_skipped(self):
        tool, _ = _make_tool()
        result = await tool._pre_process_params(count=42, flag=True)
        assert result["count"] == 42
        assert result["flag"] is True

    @pytest.mark.asyncio
    async def test_no_file_pattern_kwargs_unchanged(self):
        tool, _ = _make_tool()
        result = await tool._pre_process_params(query="hello world")
        assert result["query"] == "hello world"

    @pytest.mark.asyncio
    async def test_case_insensitive_prefix(self):
        tool, file_service = _make_tool()
        file_service.download_file.return_value = b"encoded"

        result = await tool._pre_process_params(image="file:BASE64::files/photo.png")

        assert result["image"] == base64.b64encode(b"encoded").decode()

    @pytest.mark.asyncio
    async def test_dial_url_list_grants_permissions_for_all(self):
        tool, file_service = _make_tool(
            input_schema={
                "properties": {
                    "doc_urls": {"type": "array", "items": {"type": "string"}, "dial_url": True}
                }
            },
            dial_toolset_id="my-toolset",
        )
        result = await tool._pre_process_params(
            doc_urls=[
                "file:url::files/report1.pdf",
                "file:url::files/report2.pdf",
            ]
        )
        assert result["doc_urls"] == ["files/report1.pdf", "files/report2.pdf"]
        file_service.grant_permissions_to_files.assert_awaited_once_with(
            ["files/report1.pdf", "files/report2.pdf"], "my-toolset"
        )
