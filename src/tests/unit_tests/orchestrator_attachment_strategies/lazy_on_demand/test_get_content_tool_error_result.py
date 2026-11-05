"""Verify ``_GetContentTool`` rejection errors across rejection paths.

Every error path in ``_run_in_stage_async`` raises via ``_tool_error``, whose message
must always list the accepted MIME types so the model learns the live
``input_attachment_types`` allowlist on rejection (per Concern 3 of
``docs/designs/pass_attachments_to_orchestrator.md``).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException, ToolErrorException
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.project_context import ProjectContext
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_acceptance import (
    _AttachmentAcceptance,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_materializer import (
    _AttachmentMaterializer,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool import (
    _GetContentTool,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
)
from quickapp.shared.home_path.home_path_resolver import HomePathResolver


def _make_tool(
    input_attachment_types: list[str] | None,
    messages: list[Message] | None = None,
    promoter: DialFilePromoter | None = None,
    project: ProjectContext | None = None,
) -> _GetContentTool:
    caps = OrchestratorCapabilities(
        deployment=SimpleNamespace(  # type: ignore[arg-type]
            id="test-orchestrator", input_attachment_types=input_attachment_types
        )
    )
    acceptance = _AttachmentAcceptance(caps)
    messages_mixin = MagicMock(spec=MessagesMixin)
    messages_mixin.messages = messages or []
    settings = MagicMock(spec=DialSettings)
    settings.url = "https://dial.local"
    if promoter is None:
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock()
    materializer = _AttachmentMaterializer(
        dial_promoter=promoter,
        dial_settings=settings,
        project=project,
    )
    home_resolver = MagicMock(spec=HomePathResolver)
    home_resolver.resolve_appdata_url = AsyncMock(
        side_effect=lambda path: f"files/bucket/appdata/app/home/{path}"
    )
    return _GetContentTool(
        stage_wrapper_builder=MagicMock(),
        contexts=[],
        tool_config=GET_CONTENT_TOOL_CONFIG,
        perf_timer=MagicMock(),
        attachment_acceptance=acceptance,
        messages_mixin=messages_mixin,
        deferred_stage_close_registry=MagicMock(),
        materializer=materializer,
        home_resolver=home_resolver,
    )


def _user_msg_with(attachment: Attachment) -> Message:
    return Message(
        role=Role.USER,
        content="hi",
        custom_content=CustomContent(attachments=[attachment]),
    )


async def _run_expecting_error(tool: _GetContentTool, attachment_url: str | None) -> str:
    with pytest.raises(ToolErrorException) as excinfo:
        await tool._run_in_stage_async(stage_wrapper=None, attachment_url=attachment_url)
    return excinfo.value.error_message


class TestErrorResultPayload:
    @pytest.mark.asyncio
    async def test_empty_attachment_url_includes_accepted_types(self):
        tool = _make_tool(["application/pdf", "text/csv"])

        message = await _run_expecting_error(tool, None)

        assert "Missing or empty attachment_url." in message
        assert "Accepted MIME types: application/pdf, text/csv." in message

    @pytest.mark.asyncio
    async def test_dial_url_inferred_mime_not_accepted_includes_accepted_types(self):
        # A DIAL files/ url is accepted without an allow-set, but its inferred MIME
        # must still pass the orchestrator gate; rejection carries accepted_types.
        tool = _make_tool(["application/pdf"])

        message = await _run_expecting_error(tool, "files/bucket/archive.zip")

        assert "Orchestrator deployment does not accept this file type." in message
        assert "Accepted MIME types: application/pdf." in message

    @pytest.mark.asyncio
    async def test_unsupported_scheme_includes_accepted_types(self):
        # An allowed user attachment whose url scheme is neither DIAL nor http(s)
        # (e.g. ftp:) cannot be materialised — funnels through the storage-path error.
        url = "ftp://example.com/foo.pdf"
        attachment = Attachment(title="foo.pdf", url=url, type="application/pdf")
        tool = _make_tool(["application/pdf"], messages=[_user_msg_with(attachment)])

        message = await _run_expecting_error(tool, url)

        assert "Unsupported file reference." in message
        assert "Accepted MIME types: application/pdf." in message

    @pytest.mark.asyncio
    async def test_external_promotion_blocked_includes_accepted_types(self):
        url = "https://example.com/foo.pdf"
        attachment = Attachment(title="foo.pdf", url=url, type="application/pdf")
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            side_effect=InvalidToolCallParameterException(
                parameter_name="attachment_url",
                message="External URL fetching is disabled by operator policy.",
            )
        )
        tool = _make_tool(
            ["application/pdf"], messages=[_user_msg_with(attachment)], promoter=promoter
        )

        message = await _run_expecting_error(tool, url)

        assert "External URL fetching is disabled by operator policy." in message
        assert "Accepted MIME types: application/pdf." in message

    @pytest.mark.asyncio
    async def test_no_accepted_types_line_when_input_attachment_types_none(self):
        tool = _make_tool(None)

        message = await _run_expecting_error(tool, None)

        assert "Accepted MIME types" not in message

    @pytest.mark.asyncio
    async def test_accepted_types_preserves_wildcard_patterns(self):
        tool = _make_tool(["image/*", "application/pdf"])

        message = await _run_expecting_error(tool, None)

        assert "Accepted MIME types: image/*, application/pdf." in message

    @pytest.mark.asyncio
    async def test_failure_is_converted_to_error_result_by_the_base_tool(self):
        tool = _make_tool(["application/pdf"])

        result = await tool.arun("call-1", attachment_url=None)

        assert result.is_error is True
        assert "Accepted MIME types: application/pdf." in result.content
