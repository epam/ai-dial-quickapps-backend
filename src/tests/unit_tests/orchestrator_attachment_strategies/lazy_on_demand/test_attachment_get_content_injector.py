import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_get_content_injector import (
    _AttachmentGetContentInjector,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_materializer import (
    _AttachmentMaterializer,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool_response import (
    GetContentStatus,
    GetContentToolResponse,
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


def _file_meta(url: str, name: str, content_type: str) -> SimpleNamespace:
    """Lightweight stand-in for ``aidial_client`` ``FileMetadata``."""
    return SimpleNamespace(url=url, name=name, content_type=content_type)


def _materializer(
    promoter: DialFilePromoter | None = None,
    dial_url: str = "https://dial.local",
) -> _AttachmentMaterializer:
    settings = MagicMock(spec=DialSettings)
    settings.url = dial_url
    if promoter is None:
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock()  # external promotion never reached for DIAL urls
    return _AttachmentMaterializer(
        dial_promoter=promoter,
        dial_settings=settings,
    )


def _injector(
    input_attachment_types: list[str] | None,
    materializer: _AttachmentMaterializer | None = None,
) -> _AttachmentGetContentInjector:
    caps = MagicMock(spec=OrchestratorCapabilities)
    caps.input_attachment_types = input_attachment_types
    return _AttachmentGetContentInjector(
        orchestrator_capabilities=caps,
        materializer=materializer if materializer is not None else _materializer(),
    )


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
            # the synthetic call carries the `file:url::` prefix; the attachment itself
            # keeps the bare url
            assert json.loads(assistant.tool_calls[0].function.arguments) == {
                "attachment_url": f"file:url::{expected_url}"
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


class TestExternalUrlPromotion:
    @pytest.mark.asyncio
    async def test_external_attachment_promoted_into_synthetic_pair(self):
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            return_value=_file_meta("files/bucket/report.pdf", "report.pdf", "application/pdf")
        )
        injector = _injector(
            ["application/pdf"],
            materializer=_materializer(promoter=promoter),
        )
        ext = _attachment("report.pdf", "https://example.com/report.pdf", "application/pdf")
        messages = [_user_msg("latest", [ext])]

        result = await injector.transform(messages)

        promoter.promote.assert_awaited_once_with(
            "https://example.com/report.pdf", parameter_name="attachment_url"
        )
        assert len(result) == 3
        user, assistant, tool = result
        # the model keeps seeing the original external url it can reference
        assert user.custom_content is not None
        assert user.custom_content.attachments is not None
        assert user.custom_content.attachments[0].url == "https://example.com/report.pdf"
        assert assistant.tool_calls is not None
        assert json.loads(assistant.tool_calls[0].function.arguments) == {
            "attachment_url": "file:url::https://example.com/report.pdf"
        }
        # the synthetic tool result carries the promoted DIAL attachment for the adapter
        assert tool.custom_content is not None
        assert tool.custom_content.attachments is not None
        assert tool.custom_content.attachments[0].url == "files/bucket/report.pdf"
        assert tool.custom_content.attachments[0].type == "application/pdf"
        # the tool-result text echoes the original url the model passed
        assert tool.custom_content is not None
        payload = GetContentToolResponse.from_state(tool.custom_content.state)
        assert payload is not None
        assert payload.status == GetContentStatus.SUCCESS
        assert payload.attachment_url == "file:url::https://example.com/report.pdf"
        assert 'Loaded file "report.pdf"' in str(tool.content)

    @pytest.mark.asyncio
    async def test_external_attachment_skipped_when_promotion_blocked(self):
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            side_effect=InvalidToolCallParameterException(
                parameter_name="attachment_url",
                message="External URL fetching is disabled by operator policy.",
            )
        )
        injector = _injector(["application/pdf"], materializer=_materializer(promoter=promoter))
        ext = _attachment("r.pdf", "https://example.com/r.pdf", "application/pdf")
        messages = [_user_msg("latest", [ext])]

        result = await injector.transform(messages)

        promoter.promote.assert_awaited_once()
        # no synthetic pair injected — never claim a file the orchestrator can't read
        assert result == messages

    @pytest.mark.asyncio
    async def test_external_attachment_skipped_when_resolved_mime_not_accepted(self):
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            return_value=_file_meta("files/bucket/data.bin", "data.bin", "application/zip")
        )
        injector = _injector(["application/pdf"], materializer=_materializer(promoter=promoter))
        # pre-gate passes on the declared type; the resolved content type is not accepted
        ext = _attachment("data", "https://example.com/data.pdf", "application/pdf")
        messages = [_user_msg("latest", [ext])]

        result = await injector.transform(messages)

        assert result == messages

    @pytest.mark.asyncio
    async def test_dial_attachment_is_not_promoted(self):
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock()
        injector = _injector(["application/pdf"], materializer=_materializer(promoter=promoter))
        messages = [
            _user_msg("latest", [_attachment("a.pdf", "files/bucket/a.pdf", "application/pdf")]),
        ]

        result = await injector.transform(messages)

        promoter.promote.assert_not_awaited()
        assert len(result) == 3
        assert result[2].custom_content is not None
        assert result[2].custom_content.attachments is not None
        assert result[2].custom_content.attachments[0].url == "files/bucket/a.pdf"

    @pytest.mark.asyncio
    async def test_unsupported_scheme_attachment_skipped(self):
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock()
        injector = _injector(["application/pdf"], materializer=_materializer(promoter=promoter))
        # data: scheme is classified UNSUPPORTED; declared type passes the pre-gate
        bad = _attachment("x", "data:application/pdf;base64,AAAA", "application/pdf")
        messages = [_user_msg("latest", [bad])]

        result = await injector.transform(messages)

        promoter.promote.assert_not_awaited()
        assert result == messages

    @pytest.mark.asyncio
    async def test_mixed_dial_and_external_attachments(self):
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            return_value=_file_meta("files/bucket/ext.pdf", "ext.pdf", "application/pdf")
        )
        injector = _injector(["application/pdf"], materializer=_materializer(promoter=promoter))
        messages = [
            _user_msg(
                "latest",
                [
                    _attachment("local.pdf", "files/bucket/local.pdf", "application/pdf"),
                    _attachment("remote.pdf", "https://example.com/remote.pdf", "application/pdf"),
                ],
            ),
        ]

        result = await injector.transform(messages)

        promoter.promote.assert_awaited_once_with(
            "https://example.com/remote.pdf", parameter_name="attachment_url"
        )
        assert len(result) == 5  # USER + two synthetic pairs
        local_assistant, local_tool = result[1], result[2]
        remote_assistant, remote_tool = result[3], result[4]
        assert local_tool.custom_content is not None
        assert local_tool.custom_content.attachments is not None
        assert remote_tool.custom_content is not None
        assert remote_tool.custom_content.attachments is not None
        assert local_tool.custom_content.attachments[0].url == "files/bucket/local.pdf"
        assert remote_tool.custom_content.attachments[0].url == "files/bucket/ext.pdf"
        assert local_assistant.tool_calls is not None
        assert remote_assistant.tool_calls is not None
        assert json.loads(local_assistant.tool_calls[0].function.arguments) == {
            "attachment_url": "file:url::files/bucket/local.pdf"
        }
        assert json.loads(remote_assistant.tool_calls[0].function.arguments) == {
            "attachment_url": "file:url::https://example.com/remote.pdf"
        }
