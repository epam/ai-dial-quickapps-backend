from __future__ import annotations

from collections.abc import AsyncIterable, Callable
from typing import TypeAlias, TypeVar

from quickapp.common.chat_completion_stream.models import (
    ChatStreamEvent,
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
)

TChunk = TypeVar("TChunk")

ChatStreamEventHandler: TypeAlias = Callable[[ChatStreamEvent], None]


async def consume_chat_completion_chunks(
    chunks: AsyncIterable[TChunk],
    parse_chunk: Callable[[TChunk], tuple[ChunkUsageFootprint | None, list[NormalizedChoiceDelta]]],
    on_event: ChatStreamEventHandler,
) -> None:
    async for chunk in chunks:
        footprint, deltas = parse_chunk(chunk)
        if footprint is not None:
            on_event(footprint)
        for d in deltas:
            on_event(d)
