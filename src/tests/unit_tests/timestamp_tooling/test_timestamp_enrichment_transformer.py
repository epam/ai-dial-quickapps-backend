from datetime import datetime, timezone

from aidial_sdk.chat_completion import CustomContent, Message, Role

from quickapp.common.message_metadata import (
    USER_TIMEZONE_STATE_KEY,
    MessageMetadata,
    TimestampSource,
)
from quickapp.timestamp_tooling._timestamp_enrichment_transformer import (
    _TimestampEnrichmentTransformer,
)


def _tool_msg_with_metadata(
    content: str = "tool result",
    ts: datetime | None = None,
    source: TimestampSource = TimestampSource.SERVER,
    tz_name: str = "UTC",
    content_type: str | None = None,
) -> Message:
    metadata = MessageMetadata(
        response_timestamp=ts or datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc),
        timestamp_source=source,
        timezone_name=tz_name,
        content_type=content_type,
    )
    return Message(
        role=Role.TOOL,
        content=content,
        tool_call_id="tc_1",
        custom_content=CustomContent(state=metadata.to_state_entry()),
    )


def _set_tz_tool_msg(tz_value: str | None) -> Message:
    return Message(
        role=Role.TOOL,
        content="Timezone set",
        tool_call_id="tc_tz",
        custom_content=CustomContent(state={USER_TIMEZONE_STATE_KEY: tz_value}),
    )


def test_tool_message_with_metadata_gets_annotation():
    transformer = _TimestampEnrichmentTransformer()
    msg = _tool_msg_with_metadata()
    result = transformer.transform([msg])
    assert len(result) == 1
    assert "[Timestamp: 2026-01-15 12:30:00 UTC (server default timezone)]" in str(
        result[0].content
    )


def test_non_tool_messages_pass_through():
    transformer = _TimestampEnrichmentTransformer()
    user_msg = Message(role=Role.USER, content="hello")
    assistant_msg = Message(role=Role.ASSISTANT, content="hi")
    result = transformer.transform([user_msg, assistant_msg])
    assert str(result[0].content) == "hello"
    assert str(result[1].content) == "hi"


def test_json_content_type_skipped():
    transformer = _TimestampEnrichmentTransformer()
    msg = _tool_msg_with_metadata(content_type="application/json")
    result = transformer.transform([msg])
    assert "[Timestamp:" not in str(result[0].content)


def test_user_timezone_converts_timestamp():
    transformer = _TimestampEnrichmentTransformer()
    tz_msg = _set_tz_tool_msg("Europe/Warsaw")
    tool_msg = _tool_msg_with_metadata()
    result = transformer.transform([tz_msg, tool_msg])
    # Warsaw is UTC+1 in winter
    assert "Europe/Warsaw" in str(result[1].content)
    assert "13:30:00" in str(result[1].content)


def test_reset_timezone_falls_back_to_metadata():
    transformer = _TimestampEnrichmentTransformer()
    set_msg = _set_tz_tool_msg("Europe/Warsaw")
    reset_msg = _set_tz_tool_msg(None)
    tool_msg = _tool_msg_with_metadata()
    result = transformer.transform([set_msg, reset_msg, tool_msg])
    # After reset, should use metadata timezone (UTC)
    assert "UTC" in str(result[2].content)
    assert "12:30:00" in str(result[2].content)


def test_no_metadata_message_unchanged():
    transformer = _TimestampEnrichmentTransformer()
    msg = Message(
        role=Role.TOOL,
        content="plain result",
        tool_call_id="tc_2",
    )
    result = transformer.transform([msg])
    assert str(result[0].content) == "plain result"
