import pytest
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta

from chat_stream_shared.driver import consume_chat_completion_chunks
from chat_stream_shared.models import ChunkUsageFootprint, NormalizedChoiceDelta
from chat_stream_shared.openai_parse import parse_openai_chat_completion_chunk


def _chunk(text: str) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="t",
        choices=[Choice(delta=ChoiceDelta(content=text), finish_reason=None, index=0)],
        created=0,
        model="m",
        object="chat.completion.chunk",
    )


@pytest.mark.asyncio
async def test_consume_drives_visitor_in_order():
    collected: list[str] = []

    class V:
        def on_chunk_usage(self, fp: ChunkUsageFootprint) -> None:
            collected.append(f"fp:{fp.prompt_tokens}")

        def on_choice_delta(self, delta: NormalizedChoiceDelta) -> None:
            collected.append(f"d:{delta.content or ''}")

    async def stream():
        yield _chunk("a")
        yield _chunk("b")

    await consume_chat_completion_chunks(stream(), parse_openai_chat_completion_chunk, V())
    assert collected == ["d:a", "d:b"]


@pytest.mark.asyncio
async def test_consume_calls_footprint_only_when_chunk_has_usage():
    collected: list[str] = []

    class V:
        def on_chunk_usage(self, fp: ChunkUsageFootprint) -> None:
            collected.append("fp")

        def on_choice_delta(self, delta: NormalizedChoiceDelta) -> None:
            collected.append("d")

    usage_only = ChatCompletionChunk(
        id="t",
        choices=[],
        created=0,
        model="m",
        object="chat.completion.chunk",
        usage=CompletionUsage(
            prompt_tokens=1, completion_tokens=2, total_tokens=3
        ),
    )

    async def stream():
        yield usage_only

    await consume_chat_completion_chunks(stream(), parse_openai_chat_completion_chunk, V())
    assert collected == ["fp"]
