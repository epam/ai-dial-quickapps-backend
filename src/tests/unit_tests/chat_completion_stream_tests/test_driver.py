"""Tests for ``quickapp.common.chat_completion_stream.driver``."""

import pytest

from quickapp.common.chat_completion_stream.driver import consume_chat_completion_chunks
from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint, NormalizedChoiceDelta


async def _chunks(*items):
    for x in items:
        yield x


def _parse_simple(chunk):
    if chunk == "u":
        return ChunkUsageFootprint(prompt_tokens=1, completion_tokens=1), []
    if chunk == "d":
        return None, [NormalizedChoiceDelta(content="hi")]
    return None, []


@pytest.mark.asyncio
async def test_consume_emits_footprint_then_deltas_in_order():
    events = []

    await consume_chat_completion_chunks(
        _chunks("u", "d", "d"),
        _parse_simple,
        events.append,
    )

    assert len(events) == 3
    assert isinstance(events[0], ChunkUsageFootprint)
    assert events[1].content == "hi"
    assert events[2].content == "hi"


@pytest.mark.asyncio
async def test_consume_empty_iterable():
    events = []
    await consume_chat_completion_chunks(_chunks(), _parse_simple, events.append)
    assert events == []
