"""Unit tests for chat-stream DI sinks."""

from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction

from quickapp.common.chat_completion_stream.accumulation_stream_sink import AccumulationSink
from quickapp.common.chat_completion_stream.choice_ui_stream_sink import ChoiceUiSink
from quickapp.common.chat_completion_stream.models import NormalizedChoiceDelta
from quickapp.common.chat_completion_stream.stage_wrapper_ui_stream_sink import StageWrapperUiSink
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from tests.unit_tests.stream_test_doubles import DummyStageWrapper, SpyChoice


def _tool_delta() -> NormalizedChoiceDelta:
    return NormalizedChoiceDelta(
        content=None,
        tool_calls=[
            ChoiceDeltaToolCall(
                index=0,
                id="call_1",
                type="function",
                function=ChoiceDeltaToolCallFunction(name="my_tool", arguments="{}"),
            )
        ],
    )


def test_accumulation_sink_always_records_content():
    acc = ChatStreamAccumulator()
    AccumulationSink(acc).on_delta(NormalizedChoiceDelta(content="hi", tool_calls=[]))
    assert acc.content == "hi"


def test_choice_ui_sink_noop_without_destination():
    sink = ChoiceUiSink(ChatStreamAccumulator(), destination=None)
    sink.on_stream_start()
    sink.on_delta(NormalizedChoiceDelta(content="x", tool_calls=[]))


def test_choice_ui_sink_streams_content_to_destination():
    choice = SpyChoice()
    sink = ChoiceUiSink(ChatStreamAccumulator(), destination=choice)
    sink.on_stream_start()
    sink.on_delta(NormalizedChoiceDelta(content="hello", tool_calls=[]))
    assert "\n\r" in choice.append_content_calls
    assert "hello" in choice.append_content_calls


def test_stage_wrapper_ui_sink_noop_without_wrapper():
    sink = StageWrapperUiSink(stage_wrapper=None)
    sink.on_stream_start()
    sink.on_delta(NormalizedChoiceDelta(content="x", tool_calls=[]))


def test_stage_wrapper_ui_sink_streams_content():
    wrap = DummyStageWrapper()
    sink = StageWrapperUiSink(stage_wrapper=wrap)
    sink.on_stream_start()
    sink.on_delta(NormalizedChoiceDelta(content="body", tool_calls=[]))
    wrap.stage_mock.append_content.assert_any_call("> #### Response:\n")
    wrap.stage_mock.append_content.assert_any_call("body")


def test_choice_ui_opens_tool_stage_stage_wrapper_does_not():
    choice = SpyChoice()
    wrap = DummyStageWrapper()
    tool_delta = _tool_delta()

    ChoiceUiSink(ChatStreamAccumulator(), destination=choice).on_delta(tool_delta)
    assert len(choice.created_stages) == 1

    StageWrapperUiSink(stage_wrapper=wrap).on_delta(tool_delta)
    wrap.stage_mock.create_stage.assert_not_called()
