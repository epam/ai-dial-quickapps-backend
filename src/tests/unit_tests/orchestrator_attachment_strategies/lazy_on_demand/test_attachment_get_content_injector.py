import json
from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.core.agent import OrchestratorCapabilities
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_get_content_injector import (
    _AttachmentGetContentInjector,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
)


def _user_msg(content: str = "", attachments: list[Attachment] | None = None) -> Message:
    msg = Message(role=Role.USER, content=content)
    if attachments:
        msg.custom_content = CustomContent(attachments=attachments)
    return msg


def _attachment(title: str, url: str, mime_type: str) -> Attachment:
    return Attachment(title=title, url=url, type=mime_type)


def _injector(input_attachment_types: list[str] | None) -> _AttachmentGetContentInjector:
    caps = MagicMock(spec=OrchestratorCapabilities)
    caps.input_attachment_types = input_attachment_types
    return _AttachmentGetContentInjector(orchestrator_capabilities=caps)


class TestAttachmentGetContentInjector:
    @pytest.mark.asyncio
    async def test_injects_one_pair_per_last_user_attachment(self):
        injector = _injector(["application/pdf", "text/csv"])
        messages = [
            _user_msg("first", [_attachment("old.txt", "files/bucket/old.txt", "text/plain")]),
            _user_msg(
                "latest",
                [
                    _attachment("a.pdf", "files/bucket/a.pdf", "application/pdf"),
                    _attachment("b.csv", "files/bucket/b.csv", "text/csv"),
                ],
            ),
        ]

        result = await injector.transform(messages)

        assert len(result) == 6
        assert result[0].role == Role.USER
        assert result[1].role == Role.USER

        tool_name = GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.name
        for i, expected_url in [(2, "files/bucket/a.pdf"), (4, "files/bucket/b.csv")]:
            assistant = result[i]
            tool = result[i + 1]
            assert assistant.role == Role.ASSISTANT
            assert assistant.tool_calls is not None
            assert assistant.tool_calls[0].function.name == tool_name
            assert json.loads(assistant.tool_calls[0].function.arguments) == {
                "attachment_url": expected_url
            }
            assert tool.role == Role.TOOL
            assert tool.tool_call_id == assistant.tool_calls[0].id
            assert tool.custom_content is not None
            assert tool.custom_content.attachments is not None
            assert len(tool.custom_content.attachments) == 1
            assert tool.custom_content.attachments[0].url == expected_url

    @pytest.mark.asyncio
    async def test_no_injection_without_user_attachments(self):
        injector = _injector(["application/pdf"])
        messages = [Message(role=Role.USER, content="hello")]
        result = await injector.transform(messages)
        assert result is messages

    @pytest.mark.asyncio
    async def test_idempotent_with_existing_pair_in_current_turn(self):
        injector = _injector(["application/pdf"])
        messages = [
            _user_msg("latest", [_attachment("a.pdf", "files/bucket/a.pdf", "application/pdf")]),
        ]
        first = await injector.transform(messages)
        second = await injector.transform(first)
        assert len(first) == 3
        assert len(second) == 3

    @pytest.mark.asyncio
    async def test_inserts_after_last_user_with_attachments(self):
        injector = _injector(["application/pdf"])
        messages = [
            _user_msg("turn1", [_attachment("old.pdf", "files/bucket/old.pdf", "application/pdf")]),
            Message(role=Role.ASSISTANT, content="done"),
            _user_msg("turn2", [_attachment("new.pdf", "files/bucket/new.pdf", "application/pdf")]),
        ]

        result = await injector.transform(messages)

        assert result[0].role == Role.USER
        assert result[1].role == Role.ASSISTANT
        assert result[2].role == Role.USER
        assert result[3].role == Role.ASSISTANT
        assert result[4].role == Role.TOOL
        assert result[4].custom_content is not None
        assert result[4].custom_content.attachments is not None
        assert result[4].custom_content.attachments[0].url == "files/bucket/new.pdf"

    @pytest.mark.asyncio
    async def test_skips_attachment_with_unsupported_mime(self):
        injector = _injector(["application/pdf"])
        messages = [
            _user_msg(
                "latest",
                [
                    _attachment("a.pdf", "files/bucket/a.pdf", "application/pdf"),
                    _attachment("b.txt", "files/bucket/b.txt", "text/plain"),
                ],
            ),
        ]

        result = await injector.transform(messages)

        assert len(result) == 3  # USER + ASSIST + TOOL (only for the pdf)
        assert result[2].custom_content is not None
        assert result[2].custom_content.attachments is not None
        assert result[2].custom_content.attachments[0].url == "files/bucket/a.pdf"

    @pytest.mark.asyncio
    async def test_skips_all_attachments_when_none_accepted(self):
        injector = _injector(["application/pdf"])
        messages = [
            _user_msg(
                "latest",
                [
                    _attachment("a.txt", "files/bucket/a.txt", "text/plain"),
                    _attachment("b.csv", "files/bucket/b.csv", "text/csv"),
                ],
            ),
        ]

        result = await injector.transform(messages)

        assert result == messages  # no insertion

    @pytest.mark.asyncio
    async def test_skips_attachment_when_input_attachment_types_is_none(self):
        injector = _injector(None)
        messages = [
            _user_msg("latest", [_attachment("a.pdf", "files/bucket/a.pdf", "application/pdf")]),
        ]

        result = await injector.transform(messages)

        assert result == messages

    @pytest.mark.asyncio
    async def test_uses_url_inferred_mime_when_attachment_type_missing(self):
        injector = _injector(["application/pdf"])
        # attachment.type is empty → fall back to URL filename inference
        attachment = Attachment(title="report", url="files/bucket/report.pdf", type="")
        messages = [_user_msg("latest", [attachment])]

        result = await injector.transform(messages)

        assert len(result) == 3
        assert result[2].custom_content is not None
        assert result[2].custom_content.attachments is not None
        assert result[2].custom_content.attachments[0].url == "files/bucket/report.pdf"

    @pytest.mark.asyncio
    async def test_supports_wildcard_input_attachment_types(self):
        injector = _injector(["image/*"])
        messages = [
            _user_msg(
                "latest",
                [
                    _attachment("a.png", "files/bucket/a.png", "image/png"),
                    _attachment("b.pdf", "files/bucket/b.pdf", "application/pdf"),
                ],
            ),
        ]

        result = await injector.transform(messages)

        # Only the PNG gets a synthetic pair.
        assert len(result) == 3
        assert result[2].custom_content is not None
        assert result[2].custom_content.attachments is not None
        assert result[2].custom_content.attachments[0].url == "files/bucket/a.png"
