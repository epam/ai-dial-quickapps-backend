from unittest.mock import Mock

from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta

from chat_stream_shared.openai_parse import parse_openai_chat_completion_chunk


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


def test_usage_only_chunk_footprint():
    fp, deltas = parse_openai_chat_completion_chunk(_usage_chunk(10, 20))
    assert fp.prompt_tokens == 10
    assert fp.completion_tokens == 20
    assert deltas == []


def test_content_chunk_delta():
    fp, deltas = parse_openai_chat_completion_chunk(_content_chunk("hello"))
    assert fp is None
    assert len(deltas) == 1
    assert deltas[0].content == "hello"
    assert deltas[0].custom is None
    assert deltas[0].tool_calls == ()


def test_mock_custom_content_stages_and_state():
    delta = Mock()
    delta.content = ""
    delta.custom_content = {
        "stages": [{"index": 0, "name": "Thinking"}],
        "state": {"k": "v"},
    }
    delta.tool_calls = None
    choice = Mock()
    choice.delta = delta
    chunk = Mock()
    chunk.choices = [choice]
    chunk.usage = None

    fp, deltas = parse_openai_chat_completion_chunk(chunk)
    assert fp is None
    assert len(deltas) == 1
    c = deltas[0].custom
    assert c is not None
    assert len(c.stage_entries) == 1
    assert c.stage_entries[0][0] == 0
    assert c.stage_entries[0][1]["name"] == "Thinking"
    assert c.state == {"k": "v"}
