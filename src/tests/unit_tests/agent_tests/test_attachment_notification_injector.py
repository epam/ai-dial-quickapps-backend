import json

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from pydantic.v1 import StrictStr

from quickapp.agent.processors.pre_transformers import AttachmentNotificationInjector
from quickapp.config.context import FileContextConfig
from quickapp.internal_tooling.attachment_notification_tooling._tool_configs import (
    AVAILABLE_ATTACHMENTS_TOOL_NAME,
    AVAILABLE_CONTEXT_TOOL_NAME,
)


def _user_msg(content: str = "", attachments: list[Attachment] | None = None) -> Message:
    msg = Message(role=Role.USER, content=StrictStr(content))
    if attachments:
        msg.custom_content = CustomContent(attachments=attachments)
    return msg


def _attachment(title: str, url: str, mime_type: str = "text/plain") -> Attachment:
    return Attachment(
        title=StrictStr(title),
        url=StrictStr(url),
        type=StrictStr(mime_type),
    )


def _make_injector(
    contexts: list[FileContextConfig] | None = None,
    attachments_tool_name: str = AVAILABLE_ATTACHMENTS_TOOL_NAME,
    context_tool_name: str = AVAILABLE_CONTEXT_TOOL_NAME,
) -> AttachmentNotificationInjector:
    return AttachmentNotificationInjector(
        attachments_tool_name=attachments_tool_name,
        context_tool_name=context_tool_name,
        contexts=contexts or [],
    )


class TestNoChanges:
    def test_empty_messages_no_contexts(self):
        injector = _make_injector()
        messages: list[Message] = []
        result = injector.transform(messages)
        assert result == []

    def test_no_attachments_no_contexts(self):
        injector = _make_injector()
        messages = [_user_msg("hello")]
        result = injector.transform(messages)
        assert len(result) == 1
        assert result[0].role == Role.USER

    def test_assistant_message_attachments_ignored(self):
        injector = _make_injector()
        msg = Message(
            role=Role.ASSISTANT,
            content=StrictStr("response"),
            custom_content=CustomContent(
                attachments=[_attachment("file.txt", "/files/bucket/file.txt")]
            ),
        )
        result = injector.transform([msg])
        assert len(result) == 1


class TestAttachmentInjection:
    def test_user_attachments_inject_synthetic_messages(self):
        injector = _make_injector()
        messages = [
            _user_msg(
                "check this",
                [_attachment("doc.pdf", "/files/bucket/doc.pdf", "application/pdf")],
            )
        ]
        result = injector.transform(messages)
        # Original message + assistant tool_call + tool result
        assert len(result) == 3
        assert result[0].role == Role.USER
        assert result[1].role == Role.ASSISTANT
        assert result[2].role == Role.TOOL

        # Verify tool call structure
        assert result[1].tool_calls is not None
        assert len(result[1].tool_calls) == 1
        assert result[1].tool_calls[0].function.name == AVAILABLE_ATTACHMENTS_TOOL_NAME
        assert result[1].tool_calls[0].function.arguments == "{}"

        # Verify tool result
        assert result[2].tool_call_id == result[1].tool_calls[0].id
        data = json.loads(result[2].content)
        assert len(data) == 1
        assert data[0]["title"] == "doc.pdf"
        assert data[0]["url"] == "/files/bucket/doc.pdf"
        assert data[0]["type"] == "application/pdf"
        assert data[0]["status"] == "new"

    def test_second_call_same_attachments_no_injection(self):
        injector = _make_injector()
        messages = [
            _user_msg(
                "check this",
                [_attachment("doc.pdf", "/files/bucket/doc.pdf")],
            )
        ]
        # First call: injects
        result1 = injector.transform(messages)
        assert len(result1) == 3

        # Second call: no changes, no injection
        result2 = injector.transform(messages)
        assert len(result2) == 1

    def test_new_attachment_in_subsequent_call_injects(self):
        injector = _make_injector()
        messages1 = [
            _user_msg("first", [_attachment("a.txt", "/files/a.txt")]),
        ]
        injector.transform(messages1)

        messages2 = [
            _user_msg("first", [_attachment("a.txt", "/files/a.txt")]),
            _user_msg("second", [_attachment("b.txt", "/files/b.txt")]),
        ]
        result = injector.transform(messages2)
        # 2 original + 2 synthetic
        assert len(result) == 4

        data = json.loads(result[3].content)
        assert len(data) == 2
        # a.txt is no longer new
        a_entry = next(e for e in data if e["title"] == "a.txt")
        assert "status" not in a_entry
        # b.txt is new
        b_entry = next(e for e in data if e["title"] == "b.txt")
        assert b_entry["status"] == "new"

    def test_duplicate_urls_across_messages_deduplicated(self):
        injector = _make_injector()
        att = _attachment("doc.pdf", "/files/bucket/doc.pdf")
        messages = [
            _user_msg("msg1", [att]),
            _user_msg("msg2", [att]),
        ]
        result = injector.transform(messages)
        data = json.loads(result[3].content)
        assert len(data) == 1


class TestContextInjection:
    def test_context_files_inject_synthetic_messages(self):
        ctx = FileContextConfig(url="files/bucket/ref.csv", description="Reference data")
        injector = _make_injector(contexts=[ctx])
        messages = [_user_msg("hello")]
        result = injector.transform(messages)
        # Original + assistant tool_call + tool result for context
        assert len(result) == 3
        assert result[1].role == Role.ASSISTANT
        assert result[1].tool_calls[0].function.name == AVAILABLE_CONTEXT_TOOL_NAME
        data = json.loads(result[2].content)
        assert len(data) == 1
        assert data[0]["title"] == "ref.csv"
        assert data[0]["url"] == "files/bucket/ref.csv"
        assert data[0]["description"] == "Reference data"
        assert data[0]["status"] == "new"

    def test_second_call_same_contexts_no_injection(self):
        ctx = FileContextConfig(url="files/bucket/ref.csv")
        injector = _make_injector(contexts=[ctx])
        messages = [_user_msg("hello")]
        result1 = injector.transform(messages)
        assert len(result1) == 3

        result2 = injector.transform(messages)
        assert len(result2) == 1


class TestCombinedInjection:
    def test_both_attachments_and_contexts_inject(self):
        ctx = FileContextConfig(url="files/bucket/ref.csv")
        injector = _make_injector(contexts=[ctx])
        messages = [
            _user_msg("check", [_attachment("doc.pdf", "/files/bucket/doc.pdf")])
        ]
        result = injector.transform(messages)
        # Original + 2 synthetic pairs (attachments + contexts)
        assert len(result) == 5
        # First synthetic pair: attachments
        assert result[1].tool_calls[0].function.name == AVAILABLE_ATTACHMENTS_TOOL_NAME
        # Second synthetic pair: contexts
        assert result[3].tool_calls[0].function.name == AVAILABLE_CONTEXT_TOOL_NAME
