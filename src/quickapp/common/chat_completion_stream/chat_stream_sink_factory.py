"""Build per-stream chat sinks from ChatStreamConfig (deps via sink __init__)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from injector import ProviderOf, inject

from quickapp.common.chat_completion_stream.accumulation_stream_sink import AccumulationSink
from quickapp.common.chat_completion_stream.choice_ui_stream_sink import ChoiceUiSink
from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint, NormalizedChoiceDelta
from quickapp.common.chat_completion_stream.stage_wrapper_ui_stream_sink import StageWrapperUiSink
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from quickapp.common.chat_completion_stream.stream_sink import ChatStreamSink
from quickapp.common.staged_base_tool import StagedBaseTool

if TYPE_CHECKING:
    from quickapp.common.chat_completion_stream.handler import ChatStreamConfig


def _tools_by_name(tools: list[StagedBaseTool]) -> dict[str, StagedBaseTool]:
    by_name: dict[str, StagedBaseTool] = {}
    for tool in tools:
        name = tool.openai_function_name()
        if name:
            by_name[name] = tool
    return by_name


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
    """Creates accumulator and sinks for one ``process_stream`` call.

    Tools are resolved lazily so constructing the factory (e.g. while
    AssistedBuilder builds a deployment tool) does not require
    ``list[StagedBaseTool]`` yet — that would cycle through this factory.
    """

    @inject
    def __init__(self, tools: ProviderOf[list[StagedBaseTool]]) -> None:
        self._tools: Callable[[], list[StagedBaseTool]] = tools.get

    @classmethod
    def with_defaults(cls, tools: list[StagedBaseTool] | None = None) -> "ChatStreamSinkFactory":
        """Non-DI constructor for unit tests."""
        tool_list = tools or []
        factory = cls.__new__(cls)
        factory._tools = lambda: tool_list
        return factory

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
                    tools_by_name=_tools_by_name(self._tools()),
                ),
                StageWrapperUiSink(
                    stage_wrapper=config.stage_wrapper,
                    stream_content=config.stream_content,
                ),
            ],
        )
