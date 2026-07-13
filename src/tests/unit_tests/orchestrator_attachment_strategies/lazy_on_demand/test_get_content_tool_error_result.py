"""Verify ``_GetContentTool._error_result`` payload shape across rejection paths.

Every error path in ``_run_in_stage_async`` funnels through ``_error_result``, which
must always emit an ``accepted_types`` JSON array so the model learns the live
``input_attachment_types`` allowlist on rejection (per Concern 3 of
``docs/designs/pass_attachments_to_orchestrator.md``).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_materializer import (
    _AttachmentMaterializer,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool import (
    _GetContentTool,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool_response import (
    GetContentStatus,
    GetContentToolResponse,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
)


def _make_tool(
    input_attachment_types: list[str] | None,
    messages: list[Message] | None = None,
    promoter: DialFilePromoter | None = None,
) -> _GetContentTool:
    caps = MagicMock(spec=OrchestratorCapabilities)
    caps.input_attachment_types = input_attachment_types
    caps.deployment_id = "test-orchestrator"
    caps.orchestrator_accepts_mime_type = lambda mime: bool(
        mime and input_attachment_types and any(mime == t for t in input_attachment_types)
    )
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
        contexts=[],
        tool_config=GET_CONTENT_TOOL_CONFIG,
        perf_timer=MagicMock(),
        orchestrator_capabilities=caps,
        messages_mixin=messages_mixin,
        deferred_stage_close_registry=MagicMock(),
        materializer=materializer,
    )


def _user_msg_with(attachment: Attachment) -> Message:
    return Message(
        role=Role.USER,
        content="hi",
        custom_content=CustomContent(attachments=[attachment]),
    )


class TestErrorResultPayload:
    @pytest.mark.asyncio
    async def test_empty_attachment_url_includes_accepted_types(self):
        tool = _make_tool(["application/pdf", "text/csv"])

        result = await tool._run_in_stage_async(stage_wrapper=None, attachment_url=None)

        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.status == GetContentStatus.FAIL
        assert payload.status_message == "Missing or empty attachment_url."
        assert payload.accepted_types == ["application/pdf", "text/csv"]

    @pytest.mark.asyncio
    async def test_dial_url_inferred_mime_not_accepted_includes_accepted_types(self):
        # A DIAL files/ url is accepted without an allow-set, but its inferred MIME
        # must still pass the orchestrator gate; rejection carries accepted_types.
        tool = _make_tool(["application/pdf"])

        result = await tool._run_in_stage_async(
            stage_wrapper=None, attachment_url="files/bucket/archive.zip"
        )

        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.status == GetContentStatus.FAIL
        assert payload.status_message == "Orchestrator deployment does not accept this file type."
        assert payload.accepted_types == ["application/pdf"]

    @pytest.mark.asyncio
    async def test_unsupported_scheme_includes_accepted_types(self):
        # An allowed user attachment whose url scheme is neither DIAL nor http(s)
        # (e.g. ftp:) cannot be materialised — funnels through the storage-path error.
        url = "ftp://example.com/foo.pdf"
        attachment = Attachment(title="foo.pdf", url=url, type="application/pdf")
        tool = _make_tool(["application/pdf"], messages=[_user_msg_with(attachment)])

        result = await tool._run_in_stage_async(stage_wrapper=None, attachment_url=url)

        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.status == GetContentStatus.FAIL
        assert payload.status_message == "Invalid storage path for attachment file."
        assert payload.accepted_types == ["application/pdf"]

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

        result = await tool._run_in_stage_async(stage_wrapper=None, attachment_url=url)

        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.status == GetContentStatus.FAIL
        assert payload.status_message == "External URL fetching is disabled by operator policy."
        assert payload.accepted_types == ["application/pdf"]

    @pytest.mark.asyncio
    async def test_accepted_types_empty_list_when_input_attachment_types_none(self):
        tool = _make_tool(None)

        result = await tool._run_in_stage_async(stage_wrapper=None, attachment_url=None)

        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.accepted_types == []

    @pytest.mark.asyncio
    async def test_accepted_types_preserves_wildcard_patterns(self):
        tool = _make_tool(["image/*", "application/pdf"])

        result = await tool._run_in_stage_async(stage_wrapper=None, attachment_url=None)

        payload = GetContentToolResponse.from_state(result.state)
        assert payload is not None
        assert payload.accepted_types == ["image/*", "application/pdf"]
