import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.config.tools.mcp import MCPTool
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.file_transfer._file_argument_transformer import _FileArgumentTransformer
from quickapp.file_transfer._file_loader_service import FileLoaderService
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper
from quickapp.mcp_tooling._mcp_tool import _MCPTool
from quickapp.mcp_tooling._mcp_toolset_client import _MCPToolsetClient
from tests.unit_tests.common.common import noop_timeout_resolver

DIAL_URL = "https://dial.example.com"


def _make_tool(
    input_schema: dict | None = None,
    dial_toolset_id: str | None = None,
) -> tuple[_MCPTool, MagicMock, MagicMock]:
    """Create an _MCPTool with mocked dependencies.

    Returns the tool, the mocked DialFileService (for permission-grant
    assertions), and the mocked FileLoaderService (for load assertions).
    """
    tool = SimpleNamespace(
        name="test_tool",
        description="Test tool",
        inputSchema=input_schema or {},
    )
    tool_config = MagicMock(spec=MCPTool)
    tool_config.attachment = MagicMock()
    tool_config.attachment.supported_types = []
    toolset_client = MagicMock(spec=_MCPToolsetClient)
    stage_wrapper_builder = MagicMock()
    stage_wrapper_builder.build.return_value = MagicMock(spec=_MCPStageWrapper)
    state_holder = StateHolder()
    attachment_service = MagicMock(spec=AttachmentService)
    perf_timer = PerformanceTimer()
    file_service = MagicMock(spec=DialFileService)
    file_service.grant_permissions_to_files = AsyncMock()

    file_loader = MagicMock(spec=FileLoaderService)
    file_loader.load = AsyncMock()
    file_transformer = _FileArgumentTransformer(file_service=file_loader)

    dial_settings = MagicMock(spec=DialSettings)
    dial_settings.url = DIAL_URL

    mcp_tool = _MCPTool(
        tool=tool,
        tool_config=tool_config,
        toolset_client=toolset_client,
        stage_wrapper_builder=stage_wrapper_builder,
        state_holder=state_holder,
        dial_attachment_service=attachment_service,
        perf_timer=perf_timer,
        file_service=file_service,
        dial_toolset_id=dial_toolset_id,
        login_service=MagicMock(),
        timeout_resolver=noop_timeout_resolver(),
        dial_settings=dial_settings,
        argument_transformers=[file_transformer],
    )
    return mcp_tool, file_service, file_loader


class TestPreProcessParams:
    @pytest.mark.asyncio
    async def test_base64_prefix(self):
        tool, _, file_loader = _make_tool()
        raw = b"binary data"
        file_loader.load.return_value = raw

        result = await tool._pre_process_params(image="file:base64::files/photo.png")

        file_loader.load.assert_awaited_once_with("files/photo.png", parameter_name="image")
        assert result["image"] == base64.b64encode(raw).decode()

    @pytest.mark.asyncio
    async def test_text_prefix(self):
        tool, _, file_loader = _make_tool()
        file_loader.load.return_value = b"decoded text"

        result = await tool._pre_process_params(content="file:text::files/doc.txt")

        file_loader.load.assert_awaited_once_with("files/doc.txt", parameter_name="content")
        assert result["content"] == "decoded text"

    @pytest.mark.asyncio
    async def test_url_prefix_no_dial_url(self):
        tool, _, _ = _make_tool(input_schema={"properties": {"link": {"type": "string"}}})
        result = await tool._pre_process_params(link="file:url::https://example.com/data")
        assert result["link"] == "https://example.com/data"

    @pytest.mark.asyncio
    async def test_url_prefix_with_dial_url_true(self):
        tool, file_service, _ = _make_tool(
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
        tool, file_service, _ = _make_tool(
            input_schema={"properties": {"doc_url": {"type": "string", "dial_url": False}}},
        )
        result = await tool._pre_process_params(doc_url="file:url::files/report.pdf")
        assert result["doc_url"] == "files/report.pdf"
        file_service.grant_permissions_to_files.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_prefix_raises_exception(self):
        tool, _, _ = _make_tool()
        with pytest.raises(InvalidToolCallParameterException, match="Missing required file prefix"):
            await tool._pre_process_params(param="file:files/some.txt")

    @pytest.mark.asyncio
    async def test_non_string_values_skipped(self):
        tool, _, _ = _make_tool()
        result = await tool._pre_process_params(count=42, flag=True)
        assert result["count"] == 42
        assert result["flag"] is True

    @pytest.mark.asyncio
    async def test_no_file_pattern_kwargs_unchanged(self):
        tool, _, _ = _make_tool()
        result = await tool._pre_process_params(query="hello world")
        assert result["query"] == "hello world"

    @pytest.mark.asyncio
    async def test_case_insensitive_prefix(self):
        tool, _, file_loader = _make_tool()
        file_loader.load.return_value = b"encoded"

        result = await tool._pre_process_params(image="file:BASE64::files/photo.png")

        assert result["image"] == base64.b64encode(b"encoded").decode()

    @pytest.mark.asyncio
    async def test_dial_url_list_grants_permissions_for_all(self):
        tool, file_service, _ = _make_tool(
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

    @pytest.mark.asyncio
    async def test_dial_url_external_string_rejected_with_clear_message(self):
        tool, file_service, _ = _make_tool(
            input_schema={"properties": {"doc_url": {"type": "string", "dial_url": True}}},
            dial_toolset_id="my-toolset",
        )
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._pre_process_params(doc_url="file:url::https://example.com/external.pdf")
        message = str(excinfo.value)
        assert "external URL" in message
        assert "file:data::" in message or "file:base64::" in message or "file:text::" in message
        file_service.grant_permissions_to_files.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dial_url_unsupported_scheme_rejected(self):
        tool, file_service, _ = _make_tool(
            input_schema={"properties": {"doc_url": {"type": "string", "dial_url": True}}},
            dial_toolset_id="my-toolset",
        )
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._pre_process_params(doc_url="ftp://example.com/x")
        assert "unsupported URL" in str(excinfo.value)
        file_service.grant_permissions_to_files.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dial_url_home_relative_path_rejected(self):
        # A schemeless workspace-relative path is not resolvable to a shareable
        # DIAL file here; it must keep failing like any unsupported reference.
        tool, file_service, _ = _make_tool(
            input_schema={"properties": {"doc_url": {"type": "string", "dial_url": True}}},
            dial_toolset_id="my-toolset",
        )
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._pre_process_params(doc_url="reports/img.png")
        assert "unsupported URL" in str(excinfo.value)
        file_service.grant_permissions_to_files.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dial_url_list_with_one_external_rejects_whole_list(self):
        tool, file_service, _ = _make_tool(
            input_schema={
                "properties": {
                    "doc_urls": {"type": "array", "items": {"type": "string"}, "dial_url": True}
                }
            },
            dial_toolset_id="my-toolset",
        )
        with pytest.raises(InvalidToolCallParameterException):
            await tool._pre_process_params(
                doc_urls=["files/a.pdf", "https://external.example/b.pdf"]
            )
        file_service.grant_permissions_to_files.assert_not_awaited()
