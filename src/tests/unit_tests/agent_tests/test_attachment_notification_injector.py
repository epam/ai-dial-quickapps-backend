import json

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from pydantic.v1 import StrictStr

from quickapp.agent.processors.pre_transformers import AttachmentNotificationInjector
from quickapp.config.context import FileContextConfig
from quickapp.internal_tooling.attachment_notification_tooling._tool_configs import (
    AVAILABLE_CONTEXT_TOOL_NAME,
)


def _user_msg(content: str = "", attachments: list[Attachment] | None = None) -> Message:
    msg = Message(role=Role.USER, content=StrictStr(content))
    if attachments:
        msg.custom_content = CustomContent(attachments=attachments)
    return msg


def _make_injector(
    contexts: list[FileContextConfig] | None = None,
    context_tool_name: str = AVAILABLE_CONTEXT_TOOL_NAME,
) -> AttachmentNotificationInjector:
    return AttachmentNotificationInjector(
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

    def test_context_removal_injects_removed_entry(self):
        ctx = FileContextConfig(url="files/bucket/ref.csv")
        contexts: list[FileContextConfig] = [ctx]
        injector = _make_injector(contexts=contexts)
        messages = [_user_msg("hello")]

        # First call: context present
        result1 = injector.transform(messages)
        assert len(result1) == 3

        # Remove the context
        contexts.clear()

        # Second call: removal detected, synthetic message with removed entry
        result2 = injector.transform(messages)
        assert len(result2) == 3
        data2 = json.loads(result2[2].content)
        assert len(data2) == 1
        assert data2[0]["title"] == "ref.csv"
        assert data2[0]["url"] == "files/bucket/ref.csv"
        assert data2[0]["status"] == "removed"

    def test_context_lifecycle_add_remove_all(self):
        file_a = FileContextConfig(url="files/bucket/a.csv", description="File A")
        file_b = FileContextConfig(url="files/bucket/b.pdf")
        contexts: list[FileContextConfig] = []
        injector = AttachmentNotificationInjector(
            context_tool_name=AVAILABLE_CONTEXT_TOOL_NAME, contexts=contexts
        )
        messages = [_user_msg("hello")]

        # Step 1: no contexts — no injection
        result1 = injector.transform(messages)
        assert len(result1) == 1

        # Step 2: add 2 files — both reported as new
        contexts.extend([file_a, file_b])
        result2 = injector.transform(messages)
        assert len(result2) == 3
        data2 = json.loads(result2[2].content)
        assert len(data2) == 2
        by_title = {e["title"]: e for e in data2}
        assert by_title["a.csv"]["status"] == "new"
        assert by_title["a.csv"]["description"] == "File A"
        assert by_title["b.pdf"]["status"] == "new"

        # Step 3: same files, no change — no injection
        result2b = injector.transform(messages)
        assert len(result2b) == 1

        # Step 4: remove file_b — file_a still present, file_b reported as removed
        contexts.remove(file_b)
        result3 = injector.transform(messages)
        assert len(result3) == 3
        data3 = json.loads(result3[2].content)
        assert len(data3) == 2
        by_title3 = {e["title"]: e for e in data3}
        assert "status" not in by_title3["a.csv"]
        assert by_title3["b.pdf"]["status"] == "removed"

        # Step 5: remove file_a — reported as removed
        contexts.clear()
        result4 = injector.transform(messages)
        assert len(result4) == 3
        data4 = json.loads(result4[2].content)
        assert len(data4) == 1
        assert data4[0]["title"] == "a.csv"
        assert data4[0]["status"] == "removed"

    def test_context_removal_then_no_change(self):
        ctx = FileContextConfig(url="files/bucket/ref.csv")
        contexts: list[FileContextConfig] = [ctx]
        injector = _make_injector(contexts=contexts)
        messages = [_user_msg("hello")]

        # First call: context present
        injector.transform(messages)

        # Remove the context
        contexts.clear()

        # Second call: removal detected
        injector.transform(messages)

        # Third call: no change (still empty)
        result3 = injector.transform(messages)
        assert len(result3) == 1  # no synthetic messages
