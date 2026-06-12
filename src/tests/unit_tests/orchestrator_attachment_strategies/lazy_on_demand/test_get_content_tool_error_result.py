"""Verify ``_GetContentTool._error_result`` payload shape across rejection paths.

Every error path in ``_run_in_stage_async`` funnels through ``_error_result``, which
must always emit an ``accepted_types`` JSON array so the model learns the live
``input_attachment_types`` allowlist on rejection (per Concern 3 of
``docs/designs/pass_attachments_to_orchestrator.md``).
"""

import json
from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.common.messages_mixin import MessagesMixin
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool import (
    _GetContentTool,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
)


def _make_tool(
    input_attachment_types: list[str] | None,
    messages: list[Message] | None = None,
) -> _GetContentTool:
    caps = MagicMock(spec=OrchestratorCapabilities)
    caps.input_attachment_types = input_attachment_types
    caps.deployment_id = "test-orchestrator"
    caps.orchestrator_accepts_mime_type = lambda mime: bool(
        mime and input_attachment_types and any(mime == t for t in input_attachment_types)
    )
    messages_mixin = MagicMock(spec=MessagesMixin)
    messages_mixin.messages = messages or []
    return _GetContentTool(
        stage_wrapper_builder=MagicMock(),
        contexts=[],
        tool_config=GET_CONTENT_TOOL_CONFIG,
        perf_timer=MagicMock(),
        orchestrator_capabilities=caps,
        messages_mixin=messages_mixin,
        deferred_stage_close_registry=MagicMock(),
    )


class TestErrorResultPayload:
    @pytest.mark.asyncio
    async def test_empty_attachment_url_includes_accepted_types(self):
        tool = _make_tool(["application/pdf", "text/csv"])

        result = await tool._run_in_stage_async(stage_wrapper=None, attachment_url=None)

        payload = json.loads(result.content)
        assert payload["ok"] is False
        assert payload["error"] == "Missing or empty attachment_url."
        assert payload["accepted_types"] == ["application/pdf", "text/csv"]

    @pytest.mark.asyncio
    async def test_unknown_url_includes_accepted_types(self):
        tool = _make_tool(["application/pdf"])

        result = await tool._run_in_stage_async(
            stage_wrapper=None, attachment_url="files/bucket/unknown.pdf"
        )

        payload = json.loads(result.content)
        assert payload["ok"] is False
        assert "Unknown or disallowed attachment_url" in payload["error"]
        assert payload["accepted_types"] == ["application/pdf"]

    @pytest.mark.asyncio
    async def test_invalid_storage_path_includes_accepted_types(self):
        url = "https://example.com/foo.pdf"
        attachment = Attachment(title="foo.pdf", url=url, type="application/pdf")
        messages = [
            Message(
                role=Role.USER,
                content="hi",
                custom_content=CustomContent(attachments=[attachment]),
            ),
        ]
        tool = _make_tool(["application/pdf"], messages=messages)

        result = await tool._run_in_stage_async(stage_wrapper=None, attachment_url=url)

        payload = json.loads(result.content)
        assert payload["ok"] is False
        assert payload["error"] == "Invalid storage path for attachment file."
        assert payload["accepted_types"] == ["application/pdf"]

    @pytest.mark.asyncio
    async def test_accepted_types_empty_list_when_input_attachment_types_none(self):
        tool = _make_tool(None)

        result = await tool._run_in_stage_async(stage_wrapper=None, attachment_url=None)

        payload = json.loads(result.content)
        assert payload["accepted_types"] == []

    @pytest.mark.asyncio
    async def test_accepted_types_preserves_wildcard_patterns(self):
        tool = _make_tool(["image/*", "application/pdf"])

        result = await tool._run_in_stage_async(stage_wrapper=None, attachment_url=None)

        payload = json.loads(result.content)
        assert payload["accepted_types"] == ["image/*", "application/pdf"]
