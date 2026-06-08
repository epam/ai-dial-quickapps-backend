from datetime import datetime, timezone

from aidial_sdk.chat_completion import CustomContent, Message, Role

from quickapp.common.message_metadata import (
    MESSAGE_METADATA_KEY,
    MessageMetadata,
    TimestampMetadata,
    TimestampSource,
)
from quickapp.timestamp_tooling._timestamp_annotation_transformer import (
    _TimestampAnnotationTransformer,
)
from quickapp.timestamp_tooling._tool_configs import SYNTHETIC_TIMESTAMP_CALL_PREFIX


def _tool_msg_with_metadata(
    tool_call_id: str = "call_123",
    content: str = '{"data": 42}',
    ts: datetime | None = None,
) -> Message:
    ts = ts or datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
    metadata = MessageMetadata(
        timestamp=TimestampMetadata(
            response_timestamp=ts,
            timestamp_source=TimestampSource.DEFAULT,
            timezone_name="UTC",
        )
    )
    return Message(
        role=Role.TOOL,
        content=content,
        tool_call_id=tool_call_id,
        custom_content=CustomContent(
            state={MESSAGE_METADATA_KEY: metadata.model_dump(mode="json")}
        ),
    )


class TestTimestampAnnotationTransformer:
    def test_annotates_tool_message_with_timestamp(self):
        transformer = _TimestampAnnotationTransformer()
        msg = _tool_msg_with_metadata()
        result = transformer.transform([msg])

        assert len(result) == 1
        content = str(result[0].content)
        assert "[Timestamp: 2026-01-15 12:30:00 UTC]" in content
        assert '{"data": 42}' in content

    def test_skips_synthetic_timestamp_messages(self):
        transformer = _TimestampAnnotationTransformer()
        msg = _tool_msg_with_metadata(tool_call_id=f"{SYNTHETIC_TIMESTAMP_CALL_PREFIX}abc123")
        result = transformer.transform([msg])

        content = str(result[0].content)
        assert "[Timestamp:" not in content

    def test_skips_tool_messages_without_metadata(self):
        transformer = _TimestampAnnotationTransformer()
        msg = Message(role=Role.TOOL, content="no metadata", tool_call_id="call_456")
        result = transformer.transform([msg])

        assert str(result[0].content) == "no metadata"

    def test_passes_non_tool_messages_unchanged(self):
        transformer = _TimestampAnnotationTransformer()
        user_msg = Message(role=Role.USER, content="hello")
        assistant_msg = Message(role=Role.ASSISTANT, content="world")
        result = transformer.transform([user_msg, assistant_msg])

        assert result[0] is user_msg
        assert result[1] is assistant_msg

    def test_does_not_mutate_original_message(self):
        transformer = _TimestampAnnotationTransformer()
        msg = _tool_msg_with_metadata()
        original_content = str(msg.content)

        transformer.transform([msg])

        assert str(msg.content) == original_content

    def test_mixed_messages(self):
        transformer = _TimestampAnnotationTransformer()
        user_msg = Message(role=Role.USER, content="question")
        tool_msg = _tool_msg_with_metadata()
        synthetic_msg = _tool_msg_with_metadata(
            tool_call_id=f"{SYNTHETIC_TIMESTAMP_CALL_PREFIX}xyz"
        )

        result = transformer.transform([user_msg, tool_msg, synthetic_msg])

        assert len(result) == 3
        assert result[0] is user_msg
        assert "[Timestamp:" in str(result[1].content)
        assert "[Timestamp:" not in str(result[2].content)

    def test_skips_non_string_content(self):
        transformer = _TimestampAnnotationTransformer()
        msg = _tool_msg_with_metadata()
        msg.content = [{"type": "text", "text": "data"}]  # type: ignore[assignment]

        result = transformer.transform([msg])

        assert result[0] is msg
        assert result[0].content == [{"type": "text", "text": "data"}]
