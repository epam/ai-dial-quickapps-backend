import json
from unittest.mock import MagicMock

import openai
import pytest
from aidial_sdk.chat_completion.request import (
    Attachment,
    CustomContent,
    FunctionCall,
    Message,
    Role,
    ToolCall,
)

from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_recovery_policy import (
    _GetContentRecoveryPolicy,
)


def _bad_request(message: str, body: object | None = None) -> openai.BadRequestError:
    return openai.BadRequestError(message=message, response=MagicMock(status_code=400), body=body)


def _messages_with_get_content_pair(*, with_attachment: bool = True) -> list[Message]:
    custom_content = (
        CustomContent(
            attachments=[
                Attachment(title="r.pdf", url="files/bucket/r.pdf", type="application/pdf")
            ]
        )
        if with_attachment
        else None
    )
    return [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content=" ",
            tool_calls=[
                ToolCall(
                    id="tc-gc",
                    type="function",
                    function=FunctionCall(
                        name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
                        arguments="{}",
                    ),
                )
            ],
        ),
        Message(
            role=Role.TOOL,
            content='{"ok": true}',
            tool_call_id="tc-gc",
            custom_content=custom_content,
        ),
    ]


def test_try_recover_rewrites_get_content_tool_result_on_attachment_error() -> None:
    policy = _GetContentRecoveryPolicy()
    messages = _messages_with_get_content_pair()

    changed = policy.try_recover(messages, _bad_request("unsupported file type"))

    assert changed is True
    payload = json.loads(str(messages[2].content))
    assert payload == {
        "ok": False,
        "error": "The AI model service rejected the attachment payload; the file was not forwarded.",
    }
    assert messages[2].custom_content is not None
    assert messages[2].custom_content.attachments is None


def test_try_recover_only_touches_current_turn() -> None:
    policy = _GetContentRecoveryPolicy()
    messages = [
        Message(role=Role.USER, content="turn one"),
        Message(
            role=Role.ASSISTANT,
            content=" ",
            tool_calls=[
                ToolCall(
                    id="tc-old",
                    type="function",
                    function=FunctionCall(
                        name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
                        arguments="{}",
                    ),
                )
            ],
        ),
        Message(role=Role.TOOL, content='{"ok": true}', tool_call_id="tc-old"),
        Message(role=Role.USER, content="turn two"),
    ]

    changed = policy.try_recover(messages, _bad_request("unsupported attachment"))

    assert changed is False
    assert messages[2].content == '{"ok": true}'


def test_try_recover_returns_false_on_non_bad_request() -> None:
    policy = _GetContentRecoveryPolicy()
    messages = _messages_with_get_content_pair()

    assert policy.try_recover(messages, RuntimeError("oops")) is False
    assert policy.try_recover(messages, openai.APIConnectionError(request=MagicMock())) is False
    # Attachments intact.
    assert messages[2].custom_content is not None
    assert messages[2].custom_content.attachments is not None
    assert len(messages[2].custom_content.attachments) == 1


def test_try_recover_returns_false_on_bad_request_without_attachment_signal() -> None:
    policy = _GetContentRecoveryPolicy()
    messages = _messages_with_get_content_pair()

    changed = policy.try_recover(messages, _bad_request("context length exceeded"))

    assert changed is False
    assert messages[2].content == '{"ok": true}'
    assert messages[2].custom_content is not None
    assert messages[2].custom_content.attachments is not None


@pytest.mark.parametrize(
    "signal",
    [
        "attachment payload",
        "attachment type",
        "unsupported attachment",
        "invalid attachment",
        "unsupported file",
        "invalid file",
        "input_attachment_types",
        "image_url",
        "file type",
    ],
)
def test_try_recover_matches_each_attachment_signal_in_message(signal: str) -> None:
    policy = _GetContentRecoveryPolicy()
    messages = _messages_with_get_content_pair()

    changed = policy.try_recover(messages, _bad_request(f"server says: {signal} problem"))

    assert changed is True


@pytest.mark.parametrize(
    "looks_like_attachment_word_only",
    [
        "rate limit exceeded; please retry with fewer attachments",
        "context_length_exceeded: too many attachments in conversation",
        "your request mentions an attachment but is too large",
    ],
)
def test_try_recover_ignores_bare_attachment_word_in_unrelated_errors(
    looks_like_attachment_word_only: str,
) -> None:
    """Tightened signal list rejects errors that only happen to mention
    "attachment" (rate limit, context length, etc.) without an attachment-
    specific signal phrase."""
    policy = _GetContentRecoveryPolicy()
    messages = _messages_with_get_content_pair()

    changed = policy.try_recover(messages, _bad_request(looks_like_attachment_word_only))

    assert changed is False
    assert messages[2].content == '{"ok": true}'


def test_try_recover_matches_signal_in_body_dict() -> None:
    policy = _GetContentRecoveryPolicy()
    messages = _messages_with_get_content_pair()

    body = {"error": {"code": "invalid_request", "message": "Unsupported file extension"}}
    changed = policy.try_recover(messages, _bad_request("generic", body=body))

    assert changed is True


def test_try_recover_returns_false_when_no_user_message_exists() -> None:
    policy = _GetContentRecoveryPolicy()
    messages = [
        Message(
            role=Role.ASSISTANT,
            content=" ",
            tool_calls=[
                ToolCall(
                    id="tc-gc",
                    type="function",
                    function=FunctionCall(
                        name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
                        arguments="{}",
                    ),
                )
            ],
        ),
        Message(
            role=Role.TOOL,
            content='{"ok": true}',
            tool_call_id="tc-gc",
            custom_content=CustomContent(
                attachments=[
                    Attachment(title="r.pdf", url="files/bucket/r.pdf", type="application/pdf")
                ]
            ),
        ),
    ]

    changed = policy.try_recover(messages, _bad_request("attachment rejected"))

    assert changed is False
    # History untouched.
    assert messages[1].content == '{"ok": true}'
    assert messages[1].custom_content is not None
    assert messages[1].custom_content.attachments is not None


def test_try_recover_returns_false_on_empty_messages() -> None:
    policy = _GetContentRecoveryPolicy()
    assert policy.try_recover([], _bad_request("attachment rejected")) is False
