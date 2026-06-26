"""Happy-path coverage for ``_GetContentTool._run_in_stage_async``.

Covers DIAL passthrough and the explicit-call external-promotion branch: an
allowed external url is downloaded and promoted to a durable DIAL file, the
emitted attachment carries the promoted DIAL url (recorded for the keep-policy)
while the tool-result text echoes the original url the model passed.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.common.dial_settings import DialSettings
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.utils import matches_type
from quickapp.config.context import Context, FileContextConfig
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_materializer import (
    _AttachmentMaterializer,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool import (
    _GetContentTool,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._promoted_attachment_urls import (
    PromotedAttachmentUrls,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
)
from tests.unit_tests.attachment_processing_tests._folder_context_helpers import (
    empty_expanded_context_file_urls,
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
    contexts: list[Context] | None = None,
    messages: list[Message] | None = None,
    promoter: DialFilePromoter | None = None,
    holder: PromotedAttachmentUrls | None = None,
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
        promoted_urls=holder if holder is not None else PromotedAttachmentUrls(),
    )
    return _GetContentTool(
        stage_wrapper_builder=MagicMock(),
        contexts=contexts or [],
        tool_config=GET_CONTENT_TOOL_CONFIG,
        perf_timer=MagicMock(),
        orchestrator_capabilities=caps,
        messages_mixin=messages_mixin,
        deferred_stage_close_registry=MagicMock(),
        expanded_file_urls=empty_expanded_context_file_urls(),
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
        payload = json.loads(result.content)
        assert payload["ok"] is True
        assert payload["url"] == "files/bucket/a.pdf"

    @pytest.mark.asyncio
    async def test_external_user_attachment_is_promoted(self):
        holder = PromotedAttachmentUrls()
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
            holder=holder,
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
        payload = json.loads(result.content)
        assert payload["ok"] is True
        assert payload["url"] == "https://example.com/report.pdf"
        # promoted url recorded so _GetContentKeepPolicy retains the attachment
        assert "files/bucket/report.pdf" in holder.urls

    @pytest.mark.asyncio
    async def test_external_admin_context_is_promoted(self):
        holder = PromotedAttachmentUrls()
        ctx = FileContextConfig(url="https://example.com/manual.pdf", description="manual")
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            return_value=_file_meta("files/bucket/manual.pdf", "manual.pdf", "application/pdf")
        )
        tool = _make_tool(["application/pdf"], contexts=[ctx], promoter=promoter, holder=holder)

        result = await tool._run_in_stage_async(
            stage_wrapper=None, attachment_url="https://example.com/manual.pdf"
        )

        promoter.promote.assert_awaited_once_with(
            "https://example.com/manual.pdf", parameter_name="attachment_url"
        )
        assert result.attachments is not None
        assert result.attachments[0].url == "files/bucket/manual.pdf"
        assert "files/bucket/manual.pdf" in holder.urls

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

        payload = json.loads(result.content)
        assert payload["ok"] is False
        assert payload["error"] == "Orchestrator deployment does not accept this file type."
