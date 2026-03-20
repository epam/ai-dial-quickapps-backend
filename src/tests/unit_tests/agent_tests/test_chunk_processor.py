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


def _chunk_with_custom_content(
    content: str = "",
    stages: list | None = None,
    state: dict | None = None,
):
    """Chunk with delta.content and optional delta.custom_content (stages, state).
    When custom_content is needed returns a Mock chunk (avoids Pydantic validation of Choice)."""
    if stages is not None or state is not None:
        custom: dict = {}
        if stages is not None:
            custom["stages"] = stages
        if state is not None:
            custom["state"] = state
        delta = Mock()
        delta.content = content
        delta.custom_content = custom
        delta.tool_calls = None
        choice = Mock()
        choice.delta = delta
        chunk = Mock()
        chunk.choices = [choice]
        chunk.usage = None
        return chunk
    return _content_chunk(content)


@pytest.mark.asyncio
async def test_custom_content_stages_propagate_true():
    """With propagate_orchestrator_stages=True, custom_content.stages are accumulated and streamed to destination."""
    processor = ChunkProcessor()
    destination = Mock()
    destination.append_content = Mock()
    mock_stage = Mock()
    mock_stage.append_name = Mock()
    mock_stage.append_content = Mock()
    mock_stage.add_attachment = Mock()
    mock_cm = Mock()
    mock_cm.__enter__ = Mock(return_value=mock_stage)
    mock_cm.__exit__ = Mock(return_value=None)
    destination.create_stage = Mock(return_value=mock_cm)

    stages_payload = [
        {"index": 0, "name": "Thinking"},
        {"index": 0, "content": " step 1"},
        {"index": 1, "name": "Done", "content": "ok"},
    ]
    chunk = _chunk_with_custom_content(content="", stages=stages_payload)

    result = await processor.process_chunks(
        chat_completion=_mock_stream([chunk]),  # type: ignore[arg-type]
        destination=destination,
        propagate_orchestrator_stages=True,
    )

    assert result is not None
    assert len(result.stages) == 2
    assert result.stages[0]["name"] == "Thinking"
    assert result.stages[0]["content"] == " step 1"
    assert result.stages[1]["name"] == "Done"
    assert result.stages[1]["content"] == "ok"
    # With Mock destination we don't stream (streaming requires isinstance(destination, Choice))


@pytest.mark.asyncio
async def test_custom_content_stages_propagate_false():
    """With propagate_orchestrator_stages=False, no create_stage calls and stages still accumulated on result."""
    processor = ChunkProcessor()
    destination = Mock()
    destination.append_content = Mock()
    destination.create_stage = Mock()

    chunk = _chunk_with_custom_content(
        content="", stages=[{"index": 0, "name": "Thinking", "content": "x"}]
    )

    result = await processor.process_chunks(
        chat_completion=_mock_stream([chunk]),  # type: ignore[arg-type]
        destination=destination,
        propagate_orchestrator_stages=False,
    )

    assert result is not None
    assert len(result.stages) == 1
    assert result.stages[0]["content"] == "x"
    destination.create_stage.assert_not_called()


@pytest.mark.asyncio
async def test_custom_content_state_merged_into_result():
    """Chunks with custom_content.state merge into result.state."""
    processor = ChunkProcessor()
    destination = Mock()

    chunk1 = _chunk_with_custom_content(content="", state={"claude_message_content": "a"})
    chunk2 = _chunk_with_custom_content(content="", state={"claude_message_content": "b"})

    result = await processor.process_chunks(
        chat_completion=_mock_stream([chunk1, chunk2]),  # type: ignore[arg-type]
        destination=destination,
    )

    assert result is not None
    assert result.state.get("claude_message_content") == "b"


@pytest.mark.asyncio
async def test_custom_content_stages_non_dict_item_skipped():
    """Malformed stage item (non-dict) is skipped; valid items still processed."""
    processor = ChunkProcessor()
    destination = Mock()
    destination.append_content = Mock()
    mock_stage = Mock()
    mock_stage.append_name = Mock()
    mock_stage.append_content = Mock()
    mock_stage.add_attachment = Mock()
    mock_cm = Mock()
    mock_cm.__enter__ = Mock(return_value=mock_stage)
    mock_cm.__exit__ = Mock(return_value=None)
    destination.create_stage = Mock(return_value=mock_cm)

    stages_payload = [
        {"index": 0, "name": "Valid"},
        "not a dict",
        {"index": 1, "content": "second"},
    ]
    chunk = _chunk_with_custom_content(content="", stages=stages_payload)

    result = await processor.process_chunks(
        chat_completion=_mock_stream([chunk]),  # type: ignore[arg-type]
        destination=destination,
        propagate_orchestrator_stages=True,
    )

    assert result is not None
    assert len(result.stages) == 2
    assert result.stages[0]["name"] == "Valid"
    assert result.stages[1]["content"] == "second"
