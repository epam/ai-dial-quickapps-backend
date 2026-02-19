from datetime import datetime, timezone

from quickapp.common.message_metadata import MessageMetadata, MESSAGE_METADATA_KEY


def test_from_state_none_returns_empty():
    metadata = MessageMetadata.from_state(None)
    assert metadata.response_timestamp is None


def test_from_state_empty_dict_returns_empty():
    metadata = MessageMetadata.from_state({})
    assert metadata.response_timestamp is None


def test_from_state_missing_key_returns_empty():
    metadata = MessageMetadata.from_state({"other_key": "value"})
    assert metadata.response_timestamp is None


def test_round_trip():
    now = datetime.now(timezone.utc)
    original = MessageMetadata(response_timestamp=now)
    state = original.to_state_entry()
    restored = MessageMetadata.from_state(state)
    assert restored.response_timestamp == now


def test_to_state_entry_excludes_none():
    metadata = MessageMetadata()
    entry = metadata.to_state_entry()
    assert entry == {MESSAGE_METADATA_KEY: {}}


def test_to_state_entry_includes_set_fields():
    now = datetime.now(timezone.utc)
    metadata = MessageMetadata(response_timestamp=now)
    entry = metadata.to_state_entry()
    assert "response_timestamp" in entry[MESSAGE_METADATA_KEY]


def test_extra_fields_in_state_dont_crash():
    state = {MESSAGE_METADATA_KEY: {"response_timestamp": None, "unknown_field": 42}}
    metadata = MessageMetadata.from_state(state)
    assert metadata.response_timestamp is None
