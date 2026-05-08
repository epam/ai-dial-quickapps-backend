from datetime import datetime, timezone

import pytest

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


class TestTimestampMetadataSerialization:
    def test_response_timestamp_json_dump_uses_millisecond_precision(self):
        metadata = TimestampMetadata(
            response_timestamp=datetime(2026, 3, 24, 14, 30, 0, 123456, tzinfo=timezone.utc),
        )
        dumped = metadata.model_dump(mode="json")
        assert dumped["response_timestamp"] == "2026-03-24T14:30:00.123+00:00"
        assert "123456" not in dumped["response_timestamp"]

    def test_response_timestamp_json_dump_zero_microseconds_emits_three_digits(self):
        metadata = TimestampMetadata(
            response_timestamp=datetime(2026, 3, 24, 14, 30, 0, tzinfo=timezone.utc),
        )
        dumped = metadata.model_dump(mode="json")
        assert dumped["response_timestamp"] == "2026-03-24T14:30:00.000+00:00"

    def test_response_timestamp_round_trip_preserves_milliseconds(self):
        original = TimestampMetadata(
            response_timestamp=datetime(2026, 3, 24, 14, 30, 0, 123456, tzinfo=timezone.utc),
        )
        dumped = original.model_dump(mode="json")
        restored = TimestampMetadata.model_validate(dumped)
        assert restored.response_timestamp is not None
        assert restored.response_timestamp.microsecond == 123000

    def test_response_timestamp_python_mode_dump_returns_datetime(self):
        ts = datetime(2026, 3, 24, 14, 30, 0, 123456, tzinfo=timezone.utc)
        metadata = TimestampMetadata(response_timestamp=ts)
        dumped = metadata.model_dump()
        assert dumped["response_timestamp"] == ts

    def test_none_response_timestamp_serializes_to_none(self):
        metadata = TimestampMetadata()
        dumped = metadata.model_dump(mode="json")
        assert dumped["response_timestamp"] is None

    @pytest.mark.parametrize(
        "timestamp_str,expected_microsecond",
        [
            ("2026-03-24T14:30:00+00:00", 0),
            ("2026-03-24T14:30:00.123456+00:00", 123456),
        ],
    )
    def test_legacy_timestamp_strings_still_parse(
        self, timestamp_str: str, expected_microsecond: int
    ):
        legacy = {
            "response_timestamp": timestamp_str,
            "timestamp_source": "default",
            "timezone_name": "UTC",
        }
        restored = TimestampMetadata.model_validate(legacy)
        assert restored.response_timestamp == datetime(
            2026, 3, 24, 14, 30, 0, expected_microsecond, tzinfo=timezone.utc
        )
