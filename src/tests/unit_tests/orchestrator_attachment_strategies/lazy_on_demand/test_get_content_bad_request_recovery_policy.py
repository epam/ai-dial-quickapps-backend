import json

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


def test_try_recover_rewrites_get_content_tool_result() -> None:
    policy = _GetContentRecoveryPolicy()
    messages = [
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
            custom_content=CustomContent(
                attachments=[
                    Attachment(title="r.pdf", url="files/bucket/r.pdf", type="application/pdf")
                ]
            ),
        ),
    ]

    changed = policy.try_recover(messages, Exception("bad request"))

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

    changed = policy.try_recover(messages, Exception("bad request"))

    assert changed is False
    assert messages[2].content == '{"ok": true}'
