"""Build per-stream chat sinks from ChatStreamConfig (deps via sink __init__)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from injector import inject

from quickapp.common._di_types import (
    ARGUMENT_STREAM_PRESENTATIONS,
    SUPPRESSED_TOOL_STAGE_NAMES,
    TOOL_STAGE_DISPLAY_NAMES,
)
from quickapp.common.chat_completion_stream.accumulation_stream_sink import AccumulationSink
from quickapp.common.chat_completion_stream.argument_stream_presentation import (
    ArgumentStreamPresentation,
)
from quickapp.common.chat_completion_stream.choice_ui_stream_sink import ChoiceUiSink
from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint, NormalizedChoiceDelta
from quickapp.common.chat_completion_stream.stage_wrapper_ui_stream_sink import StageWrapperUiSink
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from quickapp.common.chat_completion_stream.stream_sink import ChatStreamSink

if TYPE_CHECKING:
    from quickapp.common.chat_completion_stream.handler import ChatStreamConfig


class ChatStreamPipeline(ChatStreamSink):
    """Composite sink + accumulator for one ``process_stream`` call."""

    def __init__(self, accumulator: ChatStreamAccumulator, sinks: list[ChatStreamSink]) -> None:
        self.accumulator = accumulator
        self._sinks = sinks

    def on_stream_start(self) -> None:
        for sink in self._sinks:
            sink.on_stream_start()

    def on_delta(self, delta: NormalizedChoiceDelta) -> None:
        for sink in self._sinks:
            sink.on_delta(delta)

    def on_usage(self, usage: ChunkUsageFootprint) -> None:
        for sink in self._sinks:
            sink.on_usage(usage)

    def on_stream_success(self) -> None:
        for sink in self._sinks:
            sink.on_stream_success()

    def on_stream_failure(self) -> None:
        for sink in self._sinks:
            sink.on_stream_failure()


class ChatStreamSinkFactory:
    """Creates accumulator and sinks for one ``process_stream`` call."""

    @inject
    def __init__(
        self,
        argument_stream_presentations: ARGUMENT_STREAM_PRESENTATIONS,
        suppressed_tool_stage_names: SUPPRESSED_TOOL_STAGE_NAMES,
        tool_stage_display_names: TOOL_STAGE_DISPLAY_NAMES,
    ) -> None:
        self._argument_stream_presentations = argument_stream_presentations
        self._suppressed_tool_stage_names = suppressed_tool_stage_names
        self._tool_stage_display_names = tool_stage_display_names

    @classmethod
    def with_defaults(
        cls,
        *,
        argument_stream_presentations: dict[str, ArgumentStreamPresentation] | None = None,
        suppressed_tool_stage_names: frozenset[str] | None = None,
        tool_stage_display_names: dict[str, str] | None = None,
    ) -> "ChatStreamSinkFactory":
        """Non-DI constructor for unit tests."""
        return cls(
            argument_stream_presentations or {},
            suppressed_tool_stage_names or frozenset(),
            tool_stage_display_names or {},
        )

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
                    argument_stream_presentations=self._argument_stream_presentations,
                    suppressed_tool_stage_names=self._suppressed_tool_stage_names,
                    tool_stage_display_names=self._tool_stage_display_names,
                ),
                StageWrapperUiSink(
                    stage_wrapper=config.stage_wrapper,
                    stream_content=config.stream_content,
                ),
            ],
        )
