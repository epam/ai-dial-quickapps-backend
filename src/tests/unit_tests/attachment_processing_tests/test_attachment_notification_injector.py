import json
from types import SimpleNamespace

import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.attachment_processing._attachment_notification_injector import (
    _AttachmentNotificationInjector,
)
from quickapp.attachment_processing._tool_configs import AVAILABLE_CONTEXT_TOOL_NAME
from quickapp.config.application import ApplicationConfig, OrchestratorConfig
from quickapp.config.context import Context, FileContextConfig
from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.prompt import CustomSystemPromptConfig


def _user_msg(content: str = "", attachments: list[Attachment] | None = None) -> Message:
    msg = Message(role=Role.USER, content=content)
    if attachments:
        msg.custom_content = CustomContent(attachments=attachments)
    return msg


def _make_injector(contexts: list[Context] = None) -> _AttachmentNotificationInjector:
    """Create a fresh injector, as production does on every orchestrator iteration."""
    if contexts is None:
        contexts = []
    config = ApplicationConfig(
        contexts=contexts,
        orchestrator=OrchestratorConfig(
            deployment=DialDeploymentConfig(deployment_id="gpt-4"),
            system_prompt=CustomSystemPromptConfig(content="", variables={}),
        ),
        tool_sets=[],
    )
    provider = SimpleNamespace(get=lambda: config)
    return _AttachmentNotificationInjector(config_provider=provider)


def _extract_synthetic(result: list[Message], original_count: int) -> list[Message]:
    """Return only the synthetic messages appended after the original ones."""
    return result[original_count:]


class TestNoChanges:
    @pytest.mark.asyncio
    async def test_empty_messages_no_contexts(self):
        injector = _make_injector()
        messages: list[Message] = []
        result = await injector.transform(messages)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_attachments_no_contexts(self):
        injector = _make_injector()
        messages = [_user_msg("hello")]
        result = await injector.transform(messages)
        assert len(result) == 1
        assert result[0].role == Role.USER


class TestContextInjection:
    @pytest.mark.asyncio
    async def test_context_files_inject_synthetic_messages(self):
        ctx = FileContextConfig(url="files/bucket/ref.csv", description="Reference data")
        injector = _make_injector(contexts=[ctx])
        messages = [_user_msg("hello")]
        result = await injector.transform(messages)
        # Original + assistant tool_call + tool result for context
        assert len(result) == 3
        assert result[1].role == Role.ASSISTANT
        assert result[1].tool_calls[0].function.name == AVAILABLE_CONTEXT_TOOL_NAME
        data = json.loads(result[2].content)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["title"] == "ref.csv"
        assert data["entries"][0]["url"] == "files/bucket/ref.csv"
        assert data["entries"][0]["description"] == "Reference data"
        assert data["entries"][0]["status"] == "new"

    @pytest.mark.asyncio
    async def test_second_call_same_contexts_no_injection(self):
        """Fresh injector with history containing the same URLs produces no new messages."""
        ctx = FileContextConfig(url="files/bucket/ref.csv")
        contexts = [ctx]

        # Turn 1 — fresh injector, injects synthetic messages
        injector1 = _make_injector(contexts=contexts)
        messages = [_user_msg("hello")]
        result1 = await injector1.transform(messages)
        assert len(result1) == 3

        # Turn 2 — fresh injector, same contexts, history from turn 1
        injector2 = _make_injector(contexts=contexts)
        result2 = await injector2.transform(result1)
        assert len(result2) == 3  # unchanged, no new synthetic messages

    @pytest.mark.asyncio
    async def test_context_removal_injects_removed_entry(self):
        ctx = FileContextConfig(url="files/bucket/ref.pdf", description="Reference data")
        contexts: list[FileContextConfig] = [ctx]
        messages = [_user_msg("hello")]

        # Turn 1: context present
        injector1 = _make_injector(contexts=contexts)
        result1 = await injector1.transform(messages)
        assert len(result1) == 3

        # Remove the context
        contexts.clear()

        # Turn 2: fresh injector, empty contexts, history from turn 1
        injector2 = _make_injector(contexts=contexts)
        result2 = await injector2.transform(result1)
        assert len(result2) == 5  # 3 original + 2 new synthetic
        synthetic = _extract_synthetic(result2, 3)
        data2 = json.loads(synthetic[1].content)
        assert len(data2["entries"]) == 1
        assert data2["entries"][0]["title"] == "ref.pdf"
        assert data2["entries"][0]["url"] == "files/bucket/ref.pdf"
        assert data2["entries"][0]["type"] == "application/pdf"
        assert data2["entries"][0]["description"] == "Reference data"
        assert data2["entries"][0]["status"] == "removed"

    @pytest.mark.asyncio
    async def test_context_lifecycle_add_remove_all(self):
        file_a = FileContextConfig(url="files/bucket/a.csv", description="File A")
        file_b = FileContextConfig(url="files/bucket/b.pdf")
        contexts: list[FileContextConfig] = []
        messages = [_user_msg("hello")]

        # Step 1: no contexts — fresh injector, no injection
        injector1 = _make_injector(contexts=contexts)
        result1 = await injector1.transform(messages)
        assert len(result1) == 1

        # Step 2: add 2 files — fresh injector, both reported as new
        contexts.extend([file_a, file_b])
        injector2 = _make_injector(contexts=contexts)
        result2 = await injector2.transform(messages)
        assert len(result2) == 3
        data2 = json.loads(result2[2].content)
        assert len(data2["entries"]) == 2
        by_title = {e["title"]: e for e in data2["entries"]}
        assert by_title["a.csv"]["status"] == "new"
        assert by_title["a.csv"]["description"] == "File A"
        assert by_title["b.pdf"]["status"] == "new"

        # Step 3: same files, with history — fresh injector, no injection
        injector3 = _make_injector(contexts=contexts)
        result2b = await injector3.transform(result2)
        assert len(result2b) == 3  # unchanged

        # Step 4: remove file_b — fresh injector, file_a still present, file_b removed
        contexts.remove(file_b)
        injector4 = _make_injector(contexts=contexts)
        result3 = await injector4.transform(result2)
        assert len(result3) == 5  # 3 original + 2 new synthetic
        synthetic3 = _extract_synthetic(result3, 3)
        data3 = json.loads(synthetic3[1].content)
        assert len(data3["entries"]) == 2
        by_title3 = {e["title"]: e for e in data3["entries"]}
        assert "status" not in by_title3["a.csv"]
        assert by_title3["a.csv"]["description"] == "File A"
        assert by_title3["b.pdf"]["status"] == "removed"
        assert by_title3["b.pdf"]["type"] == "application/pdf"

        # Step 5: remove file_a — fresh injector, reported as removed
        contexts.clear()
        injector5 = _make_injector(contexts=contexts)
        result4 = await injector5.transform(result3)
        assert len(result4) == 7  # 5 original + 2 new synthetic
        synthetic4 = _extract_synthetic(result4, 5)
        data4 = json.loads(synthetic4[1].content)
        assert len(data4["entries"]) == 1
        assert data4["entries"][0]["title"] == "a.csv"
        assert data4["entries"][0]["description"] == "File A"
        assert data4["entries"][0]["status"] == "removed"

    @pytest.mark.asyncio
    async def test_description_change_triggers_renotification(self):
        """When a context description changes but URL stays the same, re-notification occurs."""
        ctx = FileContextConfig(url="files/bucket/ref.csv", description="V1")
        messages = [_user_msg("hello")]

        # Turn 1: initial injection — status: new
        injector1 = _make_injector(contexts=[ctx])
        result1 = await injector1.transform(messages)
        assert len(result1) == 3
        data1 = json.loads(result1[2].content)
        assert data1["entries"][0]["status"] == "new"
        assert data1["entries"][0]["description"] == "V1"

        # Turn 2: same URL, description changed to V2 — status: updated
        ctx_v2 = FileContextConfig(url="files/bucket/ref.csv", description="V2")
        injector2 = _make_injector(contexts=[ctx_v2])
        result2 = await injector2.transform(result1)
        assert len(result2) == 5  # 3 original + 2 new synthetic
        synthetic2 = _extract_synthetic(result2, 3)
        data2 = json.loads(synthetic2[1].content)
        assert data2["entries"][0]["status"] == "updated"
        assert data2["entries"][0]["description"] == "V2"

        # Turn 3: same URL, same description V2 — no injection (stable)
        injector3 = _make_injector(contexts=[ctx_v2])
        result3 = await injector3.transform(result2)
        assert len(result3) == 5  # unchanged

    @pytest.mark.asyncio
    async def test_context_removal_then_no_change(self):
        ctx = FileContextConfig(url="files/bucket/ref.csv")
        contexts: list[FileContextConfig] = [ctx]
        messages = [_user_msg("hello")]

        # Turn 1: context present
        injector1 = _make_injector(contexts=contexts)
        result1 = await injector1.transform(messages)

        # Remove the context
        contexts.clear()

        # Turn 2: removal detected
        injector2 = _make_injector(contexts=contexts)
        result2 = await injector2.transform(result1)

        # Turn 3: fresh injector, no change (still empty, last tool result has only removed)
        injector3 = _make_injector(contexts=contexts)
        result3 = await injector3.transform(result2)
        assert len(result3) == len(result2)  # no new synthetic messages
