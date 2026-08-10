"""Tests for incremental top-level JSON object walking."""

from quickapp.common.chat_completion_stream.json_object_argument_streamer import (
    JsonObjectArgumentStreamer,
    KeyReady,
    ObjectDone,
    StringChars,
    ValueComplete,
)


def _feed_all(chunks: list[str]):
    s = JsonObjectArgumentStreamer()
    events = []
    for chunk in chunks:
        events.extend(s.feed(chunk))
    return events, s


def test_string_field_streams_across_chunks():
    events, s = _feed_all(['{"code": "', "print(", '1)"}'])
    assert any(isinstance(e, KeyReady) and e.key == "code" for e in events)
    chars = "".join(e.text for e in events if isinstance(e, StringChars))
    assert chars == "print(1)"
    assert any(
        isinstance(e, ValueComplete) and e.key == "code" and e.value == "print(1)" for e in events
    )
    assert any(isinstance(e, ObjectDone) for e in events)
    assert s.done


def test_unescapes_string_values():
    events, _ = _feed_all([r'{"code": "a\"b\\c\n\t"}'])
    chars = "".join(e.text for e in events if isinstance(e, StringChars))
    assert chars == 'a"b\\c\n\t'


def test_nested_object_emitted_only_when_complete():
    events, _ = _feed_all(['{"cfg": {"a": 1, "b": [2, 3]}}'])
    string_events = [e for e in events if isinstance(e, StringChars)]
    assert string_events == []
    complete = [e for e in events if isinstance(e, ValueComplete)]
    assert len(complete) == 1
    assert complete[0].key == "cfg"
    assert complete[0].value == {"a": 1, "b": [2, 3]}


def test_multiple_keys_mixed_types():
    events, _ = _feed_all(['{"title": "x", "n": 3, "ok": true, "code": "y"}'])
    completes = {e.key: e.value for e in events if isinstance(e, ValueComplete)}
    assert completes == {"title": "x", "n": 3, "ok": True, "code": "y"}


def test_empty_object():
    events, s = _feed_all(["{}"])
    assert events == [ObjectDone()]
    assert s.done
