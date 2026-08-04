"""Tests for ``quickapp.common.chat_completion_stream.handler``."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion.chunks import ContentStageChunk, FinishStageChunk, StartStageChunk
from aidial_sdk.chat_completion.enums import Status
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction

from quickapp.common.chat_completion_stream.exceptions import ChatStreamParseError
from quickapp.common.chat_completion_stream.handler import (
    ChatCompletionStreamHandler,
    ChatStreamConfig,
)
from tests.unit_tests.stream_test_doubles import DummyStageWrapper, SpyChoice


async def _stream_from_chunks(*raw_chunks):
    for c in raw_chunks:
        yield c


def _chunk(*, content=None, custom_content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, custom_content=custom_content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    return SimpleNamespace(usage=None, choices=[choice], model_extra={})


def _tool_call_delta(
    *,
    index: int = 0,
    tool_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> ChoiceDeltaToolCall:
    function = None
    if name is not None or arguments is not None:
        function = ChoiceDeltaToolCallFunction(name=name, arguments=arguments)
    return ChoiceDeltaToolCall(index=index, id=tool_id, type="function", function=function)


@pytest.mark.asyncio
async def test_process_deployment_stream_accumulates_text():
    chunk = _chunk(content="abc")

    handler = ChatCompletionStreamHandler()
    wrap = DummyStageWrapper()

    acc = await handler.process_stream(
        chunks=_stream_from_chunks(chunk),
        config=ChatStreamConfig(stage_wrapper=wrap),
    )

    assert acc.content == "abc"
    wrap.stage_mock.append_content.assert_any_call("> #### Response:\n")
    wrap.stage_mock.append_content.assert_any_call("abc")


@pytest.mark.asyncio
async def test_process_orchestrator_stream_prepends_newline_and_streams_to_choice():
    choice_obj = SpyChoice()
    chunk = _chunk(content="x")

    handler = ChatCompletionStreamHandler()
    acc = await handler.process_stream(
        chunks=_stream_from_chunks(chunk),
        config=ChatStreamConfig(destination=choice_obj),
    )

    assert acc.content == "x"
    assert "\n\r" in choice_obj.append_content_calls
    assert "x" in choice_obj.append_content_calls


@pytest.mark.asyncio
async def test_run_wraps_generic_exception_as_chat_stream_parse_error():
    async def bad_stream():
        yield SimpleNamespace()
        raise ValueError("boom")

    handler = ChatCompletionStreamHandler()
    with pytest.raises(Exception) as excinfo:
        await handler._run(
            chat_completion=bad_stream(),
            accumulator=MagicMock(),
            config=ChatStreamConfig(stage_wrapper=DummyStageWrapper()),
        )

    assert isinstance(excinfo.value, ChatStreamParseError)
    assert "consume/parse" in str(excinfo.value)


@pytest.mark.asyncio
async def test_reasoning_stage_closes_completed_when_content_starts():
    choice = SpyChoice()
    reasoning = _chunk(
        custom_content={"stages": [{"index": 0, "name": "Thinking", "content": "hmm"}]}
    )
    answer = _chunk(content="final answer")

    handler = ChatCompletionStreamHandler()
    await handler.process_stream(
        chunks=_stream_from_chunks(reasoning, answer),
        config=ChatStreamConfig(destination=choice, propagate_stages=True),
    )

    finishes = [c for c in choice.drain_queue() if isinstance(c, FinishStageChunk)]
    assert len(finishes) == 1
    assert finishes[0].status == Status.COMPLETED
    assert finishes[0].stage_index == 0
    assert "final answer" in choice.append_content_calls


@pytest.mark.asyncio
async def test_reasoning_stage_closes_completed_when_tool_calls_start():
    choice = SpyChoice()
    reasoning = _chunk(
        custom_content={"stages": [{"index": 0, "name": "Thinking", "content": "plan"}]}
    )
    tool = _chunk(
        tool_calls=[
            _tool_call_delta(
                tool_id="call_1",
                name="internal_code_execution_python_interpreter",
                arguments='{"code":',
            )
        ]
    )

    handler = ChatCompletionStreamHandler()
    acc = await handler.process_stream(
        chunks=_stream_from_chunks(reasoning, tool),
        config=ChatStreamConfig(destination=choice, propagate_stages=True),
    )

    chunks = choice.drain_queue()
    finishes = [c for c in chunks if isinstance(c, FinishStageChunk)]
    assert len(finishes) == 1
    assert finishes[0].status == Status.COMPLETED
    assert finishes[0].stage_index == 0

    starts = [c for c in chunks if isinstance(c, StartStageChunk)]
    assert any(s.name == "Calling internal_code_execution_python_interpreter" for s in starts)
    assert "call_1" in acc.adopted_tool_stages
    assert not choice.created_stages[1]._closed  # noqa: SLF001 - adopted stage stays open


@pytest.mark.asyncio
async def test_tool_call_streams_decoded_code_parameter_not_raw_json():
    choice = SpyChoice()
    chunks = [
        _chunk(
            tool_calls=[
                _tool_call_delta(
                    tool_id="call_1",
                    name="internal_code_execution_python_interpreter",
                    arguments='{"title": "Draw", "code": "',
                )
            ]
        ),
        _chunk(tool_calls=[_tool_call_delta(arguments='print(1)\\npass"}')]),
    ]

    handler = ChatCompletionStreamHandler()
    acc = await handler.process_stream(
        chunks=_stream_from_chunks(*chunks),
        config=ChatStreamConfig(destination=choice, propagate_stages=True),
    )

    queue_chunks = choice.drain_queue()
    contents = [c.content for c in queue_chunks if isinstance(c, ContentStageChunk)]
    joined = "".join(contents)
    assert "> #### Request:" in joined
    assert "**Code to execute:**" in joined
    assert "````python\n" in joined
    assert "print(1)\npass" in joined
    assert '{"title"' not in joined
    assert "\\n" not in joined
    assert not any(isinstance(c, FinishStageChunk) for c in queue_chunks)
    adopted = acc.adopted_tool_stages["call_1"]
    assert adopted.stage is choice.created_stages[0]
    assert adopted.streamed_parameter_names == frozenset({"code"})


@pytest.mark.asyncio
async def test_unclosed_reasoning_stage_closed_completed_on_successful_stream_end():
    choice = SpyChoice()
    reasoning = _chunk(
        custom_content={"stages": [{"index": 0, "name": "Thinking", "content": "only"}]}
    )

    handler = ChatCompletionStreamHandler()
    await handler.process_stream(
        chunks=_stream_from_chunks(reasoning),
        config=ChatStreamConfig(destination=choice, propagate_stages=True),
    )

    finishes = [c for c in choice.drain_queue() if isinstance(c, FinishStageChunk)]
    assert len(finishes) == 1
    assert finishes[0].status == Status.COMPLETED


@pytest.mark.asyncio
async def test_open_reasoning_stage_closed_failed_on_stream_error():
    choice = SpyChoice()

    async def failing_stream():
        yield _chunk(custom_content={"stages": [{"index": 0, "name": "Thinking", "content": "x"}]})
        raise ValueError("boom")

    handler = ChatCompletionStreamHandler()
    with pytest.raises(ChatStreamParseError):
        await handler.process_stream(
            chunks=failing_stream(),
            config=ChatStreamConfig(destination=choice, propagate_stages=True),
        )

    finishes = [c for c in choice.drain_queue() if isinstance(c, FinishStageChunk)]
    assert len(finishes) == 1
    assert finishes[0].status == Status.FAILED


@pytest.mark.asyncio
async def test_deployment_path_does_not_open_tool_stages_on_choice():
    wrap = DummyStageWrapper()
    chunk = _chunk(tool_calls=[_tool_call_delta(tool_id="call_1", name="my_tool", arguments="{}")])

    handler = ChatCompletionStreamHandler()
    acc = await handler.process_stream(
        chunks=_stream_from_chunks(chunk),
        config=ChatStreamConfig(stage_wrapper=wrap),
    )

    assert acc.tool_calls is not None
    assert acc.adopted_tool_stages == {}
