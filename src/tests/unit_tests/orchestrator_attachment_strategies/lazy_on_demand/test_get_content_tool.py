"""Happy-path coverage for ``_GetContentTool._run_in_stage_async``.

Covers DIAL passthrough and the explicit-call external-promotion branch: an
external url is downloaded and promoted to a durable DIAL file, the emitted
attachment carries the promoted DIAL url while the tool-result text echoes the
original url the model passed. There is no in-app url allow-set — DIAL Core
authorizes ``files/`` fetches and the external-fetch policy authorizes ``http(s)``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.common.dial_settings import DialSettings
from quickapp.common.file_reference_pattern import to_file_url_reference
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.utils import matches_type
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_materializer import (
    _AttachmentMaterializer,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool import (
    _GetContentTool,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool_response import (
    GetContentToolResponse,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
)


def _file_meta(url: str, name: str, content_type: str) -> SimpleNamespace:
    return SimpleNamespace(url=url, name=name, content_type=content_type)


def _user_msg_with(attachment: Attachment) -> Message:
    return Message(
        role=Role.USER,
        content="hi",
        custom_content=CustomContent(attachments=[attachment]),
    )


def _make_tool(
    input_attachment_types: list[str],
    messages: list[Message] | None = None,
    promoter: DialFilePromoter | None = None,
) -> _GetContentTool:
    caps = MagicMock(spec=OrchestratorCapabilities)
    caps.input_attachment_types = input_attachment_types
    caps.deployment_id = "test-orchestrator"
    caps.orchestrator_accepts_mime_type = lambda mime: matches_type(mime, input_attachment_types)
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
    )
    return _GetContentTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=GET_CONTENT_TOOL_CONFIG,
        perf_timer=MagicMock(),
        orchestrator_capabilities=caps,
        messages_mixin=messages_mixin,
        deferred_stage_close_registry=MagicMock(),
        materializer=materializer,
    )


class TestGetContentTool:
    @pytest.mark.asyncio
    async def test_dial_user_attachment_passthrough(self):
        attachment = Attachment(title="a.pdf", url="files/bucket/a.pdf", type="application/pdf")
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock()
        tool = _make_tool(
            ["application/pdf"], messages=[_user_msg_with(attachment)], promoter=promoter
        )

        result = await tool._run_in_stage_async(
            stage_wrapper=None, attachment_url="files/bucket/a.pdf"
        )

        promoter.promote.assert_not_awaited()
        assert result.attachments is not None
        assert result.attachments[0].url == "files/bucket/a.pdf"
        assert result.attachments[0].type == "application/pdf"
        assert result.content_type == "text/plain"
        assert 'Loaded file "a.pdf"' in result.content
        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.status == "Success"
        assert payload.attachment_url == to_file_url_reference("files/bucket/a.pdf")

    @pytest.mark.asyncio
    async def test_external_user_attachment_is_promoted(self):
        attachment = Attachment(
            title="report.pdf", url="https://example.com/report.pdf", type="application/pdf"
        )
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            return_value=_file_meta("files/bucket/report.pdf", "report.pdf", "application/pdf")
        )
        tool = _make_tool(
            ["application/pdf"],
            messages=[_user_msg_with(attachment)],
            promoter=promoter,
        )

        result = await tool._run_in_stage_async(
            stage_wrapper=None, attachment_url="https://example.com/report.pdf"
        )

        promoter.promote.assert_awaited_once_with(
            "https://example.com/report.pdf", parameter_name="attachment_url"
        )
        # the emitted attachment carries the promoted DIAL url for the adapter
        assert result.attachments is not None
        assert result.attachments[0].url == "files/bucket/report.pdf"
        assert result.attachments[0].type == "application/pdf"
        # the tool-result text echoes the original url the model passed
        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.status == "Success"
        assert payload.attachment_url == to_file_url_reference("https://example.com/report.pdf")

    @pytest.mark.asyncio
    async def test_external_url_absent_from_contexts_and_messages_is_promoted(self):
        # No admin context, no user attachment — the url arrives only as the tool
        # argument (e.g. pasted in message text). It is still promoted; the
        # external-fetch policy is the gate, not an in-app allow-set.
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            return_value=_file_meta("files/bucket/pasted.pdf", "pasted.pdf", "application/pdf")
        )
        tool = _make_tool(["application/pdf"], promoter=promoter)

        result = await tool._run_in_stage_async(
            stage_wrapper=None, attachment_url="https://example.com/pasted.pdf"
        )

        promoter.promote.assert_awaited_once()
        assert result.attachments is not None
        assert result.attachments[0].url == "files/bucket/pasted.pdf"
        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.status == "Success"
        assert payload.attachment_url == to_file_url_reference("https://example.com/pasted.pdf")

    @pytest.mark.asyncio
    async def test_dial_url_absent_from_config_is_built_with_inferred_mime(self):
        # A DIAL files/ url that is neither a configured context nor a user
        # attachment is accepted; MIME/title are inferred and DIAL Core authorizes
        # the fetch. No promotion happens for DIAL urls.
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock()
        tool = _make_tool(["application/pdf"], promoter=promoter)

        result = await tool._run_in_stage_async(
            stage_wrapper=None, attachment_url="files/bucket/orphan.pdf"
        )

        promoter.promote.assert_not_awaited()
        assert result.attachments is not None
        assert result.attachments[0].url == "files/bucket/orphan.pdf"
        assert result.attachments[0].type == "application/pdf"
        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.status == "Success"
        assert payload.attachment_url == to_file_url_reference("files/bucket/orphan.pdf")
        assert payload.title == "orphan.pdf"

    @pytest.mark.asyncio
    async def test_external_promotion_rejected_when_mime_not_accepted(self):
        attachment = Attachment(
            title="data", url="https://example.com/data.pdf", type="application/pdf"
        )
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            return_value=_file_meta("files/bucket/data.bin", "data.bin", "application/zip")
        )
        tool = _make_tool(
            ["application/pdf"], messages=[_user_msg_with(attachment)], promoter=promoter
        )

        result = await tool._run_in_stage_async(
            stage_wrapper=None, attachment_url="https://example.com/data.pdf"
        )

        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.status == "Fail"
        assert payload.status_message == "Orchestrator deployment does not accept this file type."
