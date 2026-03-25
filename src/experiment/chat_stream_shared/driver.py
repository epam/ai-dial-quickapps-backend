from __future__ import annotations

from collections.abc import AsyncIterable, Callable
from typing import TypeVar

from experiment.chat_stream_shared.models import (
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    StreamChunkVisitor,
)

TChunk = TypeVar("TChunk")


async def consume_chat_completion_chunks(
    chunks: AsyncIterable[TChunk],
    parse_chunk: Callable[
        [TChunk], tuple[ChunkUsageFootprint | None, list[NormalizedChoiceDelta]]
    ],
    visitor: StreamChunkVisitor,
) -> None:
    async for chunk in chunks:
        usage, deltas = parse_chunk(chunk)
        if usage is not None:
            visitor.on_chunk_usage(usage)
        for d in deltas:
            visitor.on_choice_delta(d)
