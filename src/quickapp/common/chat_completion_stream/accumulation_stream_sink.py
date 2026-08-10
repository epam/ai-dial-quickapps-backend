"""Internal accumulation of stream payloads into ChatStreamAccumulator."""

from quickapp.common._stage_delta_types import as_stage_delta
from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint, NormalizedChoiceDelta
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from quickapp.common.chat_completion_stream.stream_sink import ChatStreamSink


class AccumulationSink(ChatStreamSink):
    """Always active: builds the in-memory stream result for history / execute / logs."""

    def __init__(self, accumulator: ChatStreamAccumulator, *, stream_content: bool = True) -> None:
        self._accumulator = accumulator
        self._stream_content = stream_content

    def on_stream_start(self) -> None:
        return

    def on_delta(self, delta: NormalizedChoiceDelta) -> None:
        if delta.custom is not None:
            norm = delta.custom
            self._accumulator.extend_attachments(norm.attachments)
            for position, raw in norm.stage_entries:
                self._accumulator.append_stage_delta(as_stage_delta(raw), position)
            if norm.state is not None:
                self._accumulator.merge_state(norm.state)

        if delta.content and self._stream_content:
            self._accumulator.append_content(delta.content)

        for tool_call in delta.tool_calls:
            self._accumulator.append_tool_call_delta(tool_call)

    def on_usage(self, usage: ChunkUsageFootprint) -> None:
        self._accumulator.apply_usage_footprint(usage)

    def on_stream_success(self) -> None:
        return

    def on_stream_failure(self) -> None:
        return
