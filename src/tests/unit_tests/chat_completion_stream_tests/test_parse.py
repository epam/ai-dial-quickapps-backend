"""Tests for ``quickapp.common.chat_completion_stream.parse``."""

from types import SimpleNamespace

import pytest
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction

from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint
from quickapp.common.chat_completion_stream.parse import (
    NormalizedCustomContentBuilder,
    parse_chat_completion_chunk,
)


def test_parse_chunk_usage_only_no_choices():
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=5)
    chunk = SimpleNamespace(usage=usage, choices=[])

    footprint, deltas = parse_chat_completion_chunk(chunk)

    assert footprint is not None
    assert isinstance(footprint, ChunkUsageFootprint)
    assert footprint.prompt_tokens == 3
    assert footprint.completion_tokens == 5
    assert deltas == []


def test_parse_chunk_no_usage_no_choices():
    chunk = SimpleNamespace(usage=None, choices=[])

    footprint, deltas = parse_chat_completion_chunk(chunk)

    assert footprint is None
    assert deltas == []


def test_parse_chunk_missing_choices_attribute():
    chunk = SimpleNamespace(usage=None)

    footprint, deltas = parse_chat_completion_chunk(chunk)

    assert footprint is None
    assert deltas == []


def test_parse_chunk_content_delta():
    delta = SimpleNamespace(content="hello", custom_content=None, tool_calls=None)
    choice = SimpleNamespace(delta=delta)
    chunk = SimpleNamespace(usage=None, choices=[choice])

    footprint, deltas = parse_chat_completion_chunk(chunk)

    assert footprint is None
    assert len(deltas) == 1
    assert deltas[0].content == "hello"
    assert deltas[0].custom is None
    assert deltas[0].tool_calls == ()


def test_parse_chunk_custom_content_stages_and_state():
    delta = SimpleNamespace(
        content=None,
        custom_content={
            "stages": [{"index": 0, "name": "Thinking"}],
            "state": {"k": 1},
        },
        tool_calls=None,
    )
    choice = SimpleNamespace(delta=delta)
    chunk = SimpleNamespace(usage=None, choices=[choice])

    _, deltas = parse_chat_completion_chunk(chunk)

    assert len(deltas) == 1
    custom = deltas[0].custom
    assert custom is not None
    assert custom.state == {"k": 1}
    assert custom.stage_entries == [(0, {"index": 0, "name": "Thinking"})]


def test_parse_chunk_tool_calls_list_normalized_to_tuple():
    tc = ChoiceDeltaToolCall(
        index=0,
        id="id-1",
        function=ChoiceDeltaToolCallFunction(name="fn", arguments=None),
        type="function",
    )
    delta = SimpleNamespace(content=None, custom_content=None, tool_calls=[tc])
    choice = SimpleNamespace(delta=delta)
    chunk = SimpleNamespace(usage=None, choices=[choice])

    _, deltas = parse_chat_completion_chunk(chunk)

    assert deltas[0].tool_calls == (tc,)


def test_parse_chunk_tool_calls_tuple_preserved():
    tc = ChoiceDeltaToolCall(
        index=0,
        id="id-2",
        function=ChoiceDeltaToolCallFunction(name="g", arguments=None),
        type="function",
    )
    delta = SimpleNamespace(content=None, custom_content=None, tool_calls=(tc,))
    choice = SimpleNamespace(delta=delta)
    chunk = SimpleNamespace(usage=None, choices=[choice])

    _, deltas = parse_chat_completion_chunk(chunk)

    assert deltas[0].tool_calls == (tc,)


def test_parse_chunk_empty_delta_skipped():
    choice = SimpleNamespace(delta=None)
    chunk = SimpleNamespace(usage=None, choices=[choice])

    _, deltas = parse_chat_completion_chunk(chunk)

    assert deltas == []


@pytest.mark.parametrize(
    "raw_state,expect_state",
    [
        ({}, None),
        (None, None),
    ],
)
def test_normalized_custom_content_builder_ignores_empty_or_missing_state(raw_state, expect_state):
    built = (
        NormalizedCustomContentBuilder().add_stages([{"name": "S"}]).set_state(raw_state).build()
    )
    assert built is not None
    assert built.state is expect_state


def test_normalized_custom_content_builder_add_attachments_non_list_no_op():
    b = NormalizedCustomContentBuilder().add_attachments("not-a-list").add_stages([{"name": "x"}])
    built = b.build()
    assert built is not None
    assert built.attachments == []


def test_normalized_custom_content_builder_build_empty_returns_none():
    assert NormalizedCustomContentBuilder().build() is None


def test_parse_chunk_falsy_custom_content_string_returns_no_custom():
    delta = SimpleNamespace(content="x", custom_content="unexpected-string", tool_calls=None)
    choice = SimpleNamespace(delta=delta)
    chunk = SimpleNamespace(usage=None, choices=[choice])

    _, deltas = parse_chat_completion_chunk(chunk)

    assert deltas[0].custom is None
