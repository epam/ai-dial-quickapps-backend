"""Tests for incremental JSON string field extraction."""

from quickapp.common.chat_completion_stream.json_string_field_streamer import (
    JsonStringFieldStreamer,
)


def test_extracts_code_across_chunk_boundaries():
    s = JsonStringFieldStreamer("code")
    assert s.feed('{"title": "x", "code": "') == ""
    assert s.feed("print(") == "print("
    assert s.feed('1)\\npass"}') == "1)\npass"
    assert s.done


def test_unescapes_common_sequences():
    s = JsonStringFieldStreamer("code")
    out = s.feed(r'{"code": "a\"b\\c\n\t"}')
    assert out == 'a"b\\c\n\t'
    assert s.done


def test_ignores_other_fields():
    s = JsonStringFieldStreamer("code")
    assert s.feed('{"title": "hello", "display_title": "x"}') == ""
    assert not s.started
    assert not s.done
