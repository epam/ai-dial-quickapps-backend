"""Tests for ``quickapp.common.chat_completion_stream.handler``."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from quickapp.common.chat_completion_stream.handler import (
    ChatCompletionStreamHandler,
    ChatStreamConfig,
)


async def _stream_from_chunks(*raw_chunks):
    for c in raw_chunks:
        yield c


@pytest.mark.asyncio
async def test_process_deployment_stream_accumulates_text():
    delta = SimpleNamespace(content="abc", custom_content=None, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    chunk = SimpleNamespace(usage=None, choices=[choice], model_extra={})

    handler = ChatCompletionStreamHandler()
    wrap = MagicMock()

    acc = await handler.process_deployment_stream(
        chunks=_stream_from_chunks(chunk),
        config=ChatStreamConfig(stage_wrapper=wrap),
    )

    assert acc.content == "abc"
    wrap.append_stage_content.assert_any_call("> #### Response:\n")
    wrap.append_stage_content.assert_any_call("abc")


@pytest.mark.asyncio
async def test_process_orchestrator_stream_prepends_newline_and_streams_to_choice():
    delta = SimpleNamespace(content="x", custom_content=None, tool_calls=None)
    choice_obj = MagicMock()
    stream_choice = SimpleNamespace(delta=delta, finish_reason=None)
    chunk = SimpleNamespace(usage=None, choices=[stream_choice], model_extra={})

    handler = ChatCompletionStreamHandler()
    acc = await handler.process_orchestrator_stream(
        chat_completion=_stream_from_chunks(chunk),
        config=ChatStreamConfig(destination=choice_obj),
    )

    assert acc.content == "x"
    choice_obj.append_content.assert_any_call("\n\r")
    choice_obj.append_content.assert_any_call("x")


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
            config=ChatStreamConfig(),
        )
    from quickapp.common.chat_completion_stream.exceptions import ChatStreamParseError

    assert isinstance(excinfo.value, ChatStreamParseError)
    assert "consume/parse" in str(excinfo.value)
