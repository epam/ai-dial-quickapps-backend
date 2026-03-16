from unittest.mock import Mock

import pytest
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta

from quickapp.agent.chunk_processor import ChunkProcessor


def _content_chunk(content: str) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="test",
        choices=[Choice(delta=ChoiceDelta(content=content), finish_reason=None, index=0)],
        created=0,
        model="test",
        object="chat.completion.chunk",
    )


def _usage_chunk(prompt_tokens: int, completion_tokens: int) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="test",
        choices=[],
        created=0,
        model="test",
        object="chat.completion.chunk",
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


async def _mock_stream(chunks: list[ChatCompletionChunk]):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_usage_only_chunk_is_captured():
    """Usage chunk without choices must not be skipped."""
    processor = ChunkProcessor()
    destination = Mock()

    chunks = [
        _content_chunk("hello"),
        _usage_chunk(prompt_tokens=10, completion_tokens=20),
    ]

    result = await processor.process_chunks(
        chat_completion=_mock_stream(chunks),  # type: ignore[arg-type]
        destination=destination,
    )

    assert result is not None
    assert result.usage is not None
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 20
    assert result.content == "hello"


@pytest.mark.asyncio
async def test_usage_chunk_without_any_content_chunks():
    """Stream with only a usage chunk (no content) must still capture usage."""
    processor = ChunkProcessor()
    destination = Mock()

    chunks = [_usage_chunk(prompt_tokens=5, completion_tokens=3)]

    result = await processor.process_chunks(
        chat_completion=_mock_stream(chunks),  # type: ignore[arg-type]
        destination=destination,
    )

    assert result is not None
    assert result.usage is not None
    assert result.usage.prompt_tokens == 5
    assert result.usage.completion_tokens == 3
    assert result.content == ""


@pytest.mark.asyncio
async def test_content_streamed_to_destination():
    """Content chunks are streamed to the destination choice."""
    processor = ChunkProcessor()
    destination = Mock()

    chunks = [_content_chunk("hello "), _content_chunk("world")]

    await processor.process_chunks(
        chat_completion=_mock_stream(chunks),  # type: ignore[arg-type]
        destination=destination,
    )

    content_calls = [
        call.args[0] for call in destination.append_content.call_args_list if call.args[0] != "\n\r"
    ]
    assert content_calls == ["hello ", "world"]


@pytest.mark.asyncio
async def test_no_usage_when_absent():
    """When no chunk carries usage, result.usage stays None."""
    processor = ChunkProcessor()
    destination = Mock()

    chunks = [_content_chunk("hi")]

    result = await processor.process_chunks(
        chat_completion=_mock_stream(chunks),  # type: ignore[arg-type]
        destination=destination,
    )

    assert result is not None
    assert result.usage is None
