"""Build per-stream chat sinks from ChatStreamConfig (deps via sink __init__)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quickapp.common.chat_completion_stream.accumulation_stream_sink import AccumulationSink
from quickapp.common.chat_completion_stream.choice_ui_stream_sink import ChoiceUiSink
from quickapp.common.chat_completion_stream.stage_wrapper_ui_stream_sink import StageWrapperUiSink
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from quickapp.common.chat_completion_stream.stream_sink import ChatStreamSink

if TYPE_CHECKING:
    from quickapp.common.chat_completion_stream.handler import ChatStreamConfig


class ChatStreamPipeline:
    """Accumulator + sinks wired for one ``process_stream`` call."""

    def __init__(self, accumulator: ChatStreamAccumulator, sinks: list[ChatStreamSink]) -> None:
        self.accumulator = accumulator
        self.sinks = sinks


class ChatStreamSinkFactory:
    """Creates accumulator and sinks for one ``process_stream`` call."""

    def create(self, config: ChatStreamConfig) -> ChatStreamPipeline:
        accumulator = ChatStreamAccumulator()
        return ChatStreamPipeline(
            accumulator,
            [
                AccumulationSink(accumulator, stream_content=config.stream_content),
                ChoiceUiSink(
                    accumulator,
                    destination=config.destination,
                    stream_content=config.stream_content,
                    propagate_stages=config.propagate_stages,
                    argument_stream_presentations=config.argument_stream_presentations,
                ),
                StageWrapperUiSink(
                    stage_wrapper=config.stage_wrapper,
                    stream_content=config.stream_content,
                ),
            ],
        )
