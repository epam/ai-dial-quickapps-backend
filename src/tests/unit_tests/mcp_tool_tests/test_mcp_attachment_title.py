import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

from mcp.types import BlobResourceContents, EmbeddedResource, ImageContent, TextResourceContents
from pydantic import AnyUrl

from quickapp.common.dial_settings import DialSettings
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.config.tools.mcp import MCPTool
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper
from quickapp.mcp_tooling._mcp_tool import _MCPTool
from quickapp.mcp_tooling._mcp_toolset_client import _MCPToolsetClient
from tests.unit_tests.common.common import noop_timeout_resolver

TOOL_NAME = "test_tool"


def _make_tool() -> _MCPTool:
    """Create an _MCPTool with mocked dependencies."""
    tool = SimpleNamespace(name=TOOL_NAME, description="Test tool", inputSchema={})
    tool_config = MagicMock(spec=MCPTool)
    tool_config.attachment = MagicMock()
    tool_config.attachment.supported_types = []
    stage_wrapper_builder = MagicMock()
    stage_wrapper_builder.build.return_value = MagicMock(spec=_MCPStageWrapper)
    dial_settings = MagicMock(spec=DialSettings)
    dial_settings.url = "https://dial.example.com"

    return _MCPTool(
        tool=tool,
        tool_config=tool_config,
        toolset_client=MagicMock(spec=_MCPToolsetClient),
        stage_wrapper_builder=stage_wrapper_builder,
        state_holder=StateHolder(),
        dial_attachment_service=MagicMock(spec=AttachmentService),
        perf_timer=PerformanceTimer(),
        file_service=MagicMock(spec=DialFileService),
        dial_toolset_id=None,
        login_service=MagicMock(),
        timeout_resolver=noop_timeout_resolver(),
        dial_settings=dial_settings,
    )


def _blob_resource(uri: str, mime_type: str = "application/octet-stream") -> EmbeddedResource:
    resource = BlobResourceContents(
        mimeType=mime_type,
        blob=base64.b64encode(b"blob").decode(),
        uri=AnyUrl(uri),
    )
    return EmbeddedResource(resource=resource, type="resource")


class TestAttachmentTitle:
    def test_blob_resource_uses_uri_filename(self):
        tool = _make_tool()

        attachment = tool._content_to_attachment(
            _blob_resource(
                "file:///my_report_ar_20260812-153000.docx",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        )

        assert attachment is not None
        assert attachment.title == "my_report_ar_20260812-153000.docx"

    def test_text_resource_uses_uri_filename(self):
        tool = _make_tool()
        resource = TextResourceContents(
            mimeType="text/plain",
            text="content",
            uri=AnyUrl("https://example.com/exports/summary.txt"),
        )

        attachment = tool._content_to_attachment(
            EmbeddedResource(resource=resource, type="resource")
        )

        assert attachment is not None
        assert attachment.title == "summary.txt"

    def test_uri_filename_is_url_decoded(self):
        tool = _make_tool()

        attachment = tool._content_to_attachment(
            _blob_resource("file:///q3%20report.pdf", mime_type="application/pdf")
        )

        assert attachment is not None
        # sanitize_filename collapses the decoded space so the title stays usable
        # as the `files/{bucket}/{title}` upload path segment.
        assert attachment.title == "q3-report.pdf"

    def test_uri_without_filename_falls_back_to_generated_name(self):
        tool = _make_tool()

        attachment = tool._content_to_attachment(
            _blob_resource("https://example.com/", mime_type="text/plain")
        )

        assert attachment is not None
        assert attachment.title is not None
        assert attachment.title.startswith(f"{TOOL_NAME}-")
        assert attachment.title.endswith(".txt")

    def test_image_content_keeps_generated_name(self):
        """ImageContent carries no uri, so the generated filename still applies."""
        tool = _make_tool()

        attachment = tool._content_to_attachment(
            ImageContent(
                mimeType="image/png",
                data=base64.b64encode(b"img").decode(),
                type="image",
            )
        )

        assert attachment is not None
        assert attachment.title is not None
        assert attachment.title.startswith(f"{TOOL_NAME}-")
        assert attachment.title.endswith(".png")
