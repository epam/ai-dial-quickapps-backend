from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import TypeAlias, TypeVar

from quickapp.common.chat_completion_stream.models import (
    ChatStreamEvent,
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
)

TChunk = TypeVar("TChunk")

ChatStreamChunkParser: TypeAlias = Callable[
    [TChunk], tuple[ChunkUsageFootprint | None, list[NormalizedChoiceDelta]]
]


async def iter_chat_completion_events(
    chunks: AsyncIterable[TChunk],
    parse_chunk: ChatStreamChunkParser,
) -> AsyncIterator[ChatStreamEvent]:
    async for chunk in chunks:
        footprint, deltas = parse_chunk(chunk)
        if footprint is not None:
            yield footprint
        for d in deltas:
            yield d
