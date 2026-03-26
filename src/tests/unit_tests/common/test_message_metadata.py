from datetime import datetime, timezone

from quickapp.common.message_metadata import (
    MESSAGE_METADATA_KEY,
    MessageMetadata,
    TimestampMetadata,
    TimestampSource,
    get_metadata_from_state,
    set_metadata_in_state,
)


class TestMessageMetadata:
    def test_round_trip(self):
        metadata = MessageMetadata(
            timestamp=TimestampMetadata(
                response_timestamp=datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc),
                timestamp_source=TimestampSource.DEFAULT,
                timezone_name="UTC",
            )
        )
        state: dict = {}
        set_metadata_in_state(state, metadata)

        restored = get_metadata_from_state(state)
        assert restored is not None
        assert restored.timestamp is not None
        assert restored.timestamp.response_timestamp == metadata.timestamp.response_timestamp
        assert restored.timestamp.timestamp_source == TimestampSource.DEFAULT
        assert restored.timestamp.timezone_name == "UTC"

    def test_get_from_none_state(self):
        assert get_metadata_from_state(None) is None

    def test_get_from_empty_state(self):
        assert get_metadata_from_state({}) is None

    def test_get_from_state_without_key(self):
        assert get_metadata_from_state({"other": "value"}) is None

    def test_set_creates_key(self):
        state: dict = {}
        set_metadata_in_state(state, MessageMetadata())
        assert MESSAGE_METADATA_KEY in state
