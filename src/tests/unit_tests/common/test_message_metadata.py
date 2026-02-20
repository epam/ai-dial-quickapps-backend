from datetime import datetime, timezone

from quickapp.common.message_metadata import (
    MESSAGE_METADATA_KEY,
    MessageMetadata,
    TimestampMetadata,
    TimestampSource,
)


def test_from_state_none_returns_empty():
    metadata = MessageMetadata.from_state(None)
    assert metadata.timestamp is None


def test_from_state_empty_dict_returns_empty():
    metadata = MessageMetadata.from_state({})
    assert metadata.timestamp is None


def test_from_state_missing_key_returns_empty():
    metadata = MessageMetadata.from_state({"other_key": "value"})
    assert metadata.timestamp is None


def test_round_trip():
    now = datetime.now(timezone.utc)
    original = MessageMetadata(
        timestamp=TimestampMetadata(response_timestamp=now),
    )
    state = original.to_state_entry()
    restored = MessageMetadata.from_state(state)
    assert restored.timestamp is not None
    assert restored.timestamp.response_timestamp == now


def test_to_state_entry_excludes_none():
    metadata = MessageMetadata()
    entry = metadata.to_state_entry()
    assert entry == {MESSAGE_METADATA_KEY: {}}


def test_to_state_entry_includes_set_fields():
    now = datetime.now(timezone.utc)
    metadata = MessageMetadata(
        timestamp=TimestampMetadata(response_timestamp=now),
    )
    entry = metadata.to_state_entry()
    assert "timestamp" in entry[MESSAGE_METADATA_KEY]
    assert "response_timestamp" in entry[MESSAGE_METADATA_KEY]["timestamp"]


def test_extra_fields_in_state_dont_crash():
    state = {MESSAGE_METADATA_KEY: {"timestamp": None, "unknown_field": 42}}
    metadata = MessageMetadata.from_state(state)
    assert metadata.timestamp is None


def test_round_trip_with_provenance_fields():
    now = datetime.now(timezone.utc)
    original = MessageMetadata(
        timestamp=TimestampMetadata(
            response_timestamp=now,
            timestamp_source=TimestampSource.USER_TIMEZONE,
            timezone_name="Europe/Warsaw",
        ),
        content_type="text/plain",
    )
    state = original.to_state_entry()
    restored = MessageMetadata.from_state(state)
    assert restored.timestamp is not None
    assert restored.timestamp.response_timestamp == now
    assert restored.timestamp.timestamp_source == TimestampSource.USER_TIMEZONE
    assert restored.timestamp.timezone_name == "Europe/Warsaw"
    assert restored.content_type == "text/plain"


def test_backward_compat_old_state_without_new_fields():
    now = datetime.now(timezone.utc)
    state = {MESSAGE_METADATA_KEY: {"timestamp": {"response_timestamp": now.isoformat()}}}
    metadata = MessageMetadata.from_state(state)
    assert metadata.timestamp is not None
    assert metadata.timestamp.response_timestamp is not None
    assert metadata.timestamp.timestamp_source is None
    assert metadata.timestamp.timezone_name is None
    assert metadata.content_type is None


def test_skip_time_annotation_defaults_false():
    metadata = TimestampMetadata()
    assert metadata.skip_time_annotation is False


def test_skip_time_annotation_round_trip():
    original = MessageMetadata(
        timestamp=TimestampMetadata(skip_time_annotation=True),
    )
    state = original.to_state_entry()
    restored = MessageMetadata.from_state(state)
    assert restored.timestamp is not None
    assert restored.timestamp.skip_time_annotation is True
