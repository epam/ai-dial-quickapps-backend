"""Stream UI side effects targeting the orchestrator Choice."""

from __future__ import annotations

import logging
from time import perf_counter

from aidial_sdk.chat_completion import Attachment, Choice, Stage, Status
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from quickapp.common._stage_delta_types import (
    StageDeltaItem,
    as_stage_delta,
    attachment_kwargs,
    get_stage_index,
    stage_display_name,
)
from quickapp.common.chat_completion_stream.adopted_tool_stage import AdoptedToolStage
from quickapp.common.chat_completion_stream.argument_stream_presentation import (
    ArgumentStreamPresentation,
    StreamingArgumentPresenter,
)
from quickapp.common.chat_completion_stream.exceptions import ChatStreamWriteError
from quickapp.common.chat_completion_stream.models import (
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    NormalizedCustomContent,
)
from quickapp.common.chat_completion_stream.stream_result import (
    ChatStreamAccumulator,
    ensure_attachment_url_or_data,
)
from quickapp.common.chat_completion_stream.stream_sink import ChatStreamSink
from quickapp.common.payload_logging import log_payload

logger = logging.getLogger(__name__)


class _StreamingToolStageState:
    """Mutable UI state for a tool-call stage opened while arguments are still streaming."""

    def __init__(self, stage: Stage, start_time: float, *, name_set: bool) -> None:
        self.stage = stage
        self.start_time = start_time
        self.name_set = name_set
        self.function_name: str | None = None
        self.presenter: StreamingArgumentPresenter | None = None
        self.pending_argument_chunks: list[str] = []


class ChoiceUiSink(ChatStreamSink):
    """Active when constructed with a non-None ``destination`` (orchestrator path)."""

    def __init__(
        self,
        accumulator: ChatStreamAccumulator,
        destination: Choice | None,
        *,
        stream_content: bool = True,
        propagate_stages: bool = False,
        argument_stream_presentations: dict[str, ArgumentStreamPresentation] | None = None,
        suppressed_tool_stage_names: frozenset[str] | None = None,
        tool_stage_display_names: dict[str, str] | None = None,
    ) -> None:
        self._accumulator = accumulator
        self._destination = destination
        self._stream_content = stream_content
        self._propagate_stages = propagate_stages
        self._argument_stream_presentations = argument_stream_presentations or {}
        self._suppressed_tool_stage_names = suppressed_tool_stage_names or frozenset()
        self._tool_stage_display_names = tool_stage_display_names or {}
        self._stages_by_index: dict[int, Stage] = {}
        self._tool_stages_by_index: dict[int, _StreamingToolStageState] = {}
        self._suppressed_tool_indexes: set[int] = set()

    def on_stream_start(self) -> None:
        destination = self._destination
        if destination is None:
            return
        destination.append_content("\n\r")

    def on_delta(self, delta: NormalizedChoiceDelta) -> None:
        destination = self._destination
        if destination is None:
            return

        if delta.custom is not None:
            self._apply_custom(delta.custom)

        leaving_reasoning = bool(delta.tool_calls) or bool(delta.content and self._stream_content)
        if leaving_reasoning and self._stages_by_index:
            self._close_all_streaming_stages(Status.COMPLETED)

        if delta.content and self._stream_content:
            try:
                destination.append_content(delta.content)
            except Exception as exc:  # pragma: no cover - defensive
                raise ChatStreamWriteError("Failed to stream content to destination") from exc

        for tool_call in delta.tool_calls:
            self._stream_tool_call_delta(tool_call)

    def on_usage(self, usage: ChunkUsageFootprint) -> None:
        return

    def on_stream_success(self) -> None:
        if self._destination is None:
            return
        self._publish_adopted_tool_stages()
        self._close_all_streaming_stages(Status.COMPLETED)

    def on_stream_failure(self) -> None:
        if self._destination is None:
            return
        self._close_all_streaming_stages(Status.FAILED)
        self._close_all_tool_stages(Status.FAILED)

    def _apply_custom(self, norm: NormalizedCustomContent) -> None:
        destination = self._destination
        assert destination is not None
        if norm.attachments:
            self._add_attachments(destination, norm.attachments)
        for position, raw in norm.stage_entries:
            stage_delta = as_stage_delta(raw)
            if self._propagate_stages:
                self._stream_stage_delta(stage_delta, position)

    @staticmethod
    def _add_attachments(destination: Choice, attachments: list[Attachment]) -> None:
        if not attachments:
            return
        for attachment in attachments:
            ensure_attachment_url_or_data(attachment)
            try:
                destination.add_attachment(attachment)
            except Exception as exc:
                raise ChatStreamWriteError("Failed to stream attachment.") from exc

    def _stream_tool_call_delta(self, tool_call: ChoiceDeltaToolCall) -> None:
        destination = self._destination
        assert destination is not None

        index = tool_call.index
        if index in self._suppressed_tool_indexes:
            return

        state = self._tool_stages_by_index.get(index)
        if state is None:
            function_name = None
            if tool_call.function and tool_call.function.name:
                function_name = tool_call.function.name
            if function_name is not None and function_name in self._suppressed_tool_stage_names:
                self._suppressed_tool_indexes.add(index)
                return
            stage_name = None
            if function_name is not None:
                stage_name = self._tool_stage_display_names.get(
                    function_name, f"Calling {function_name}"
                )
            try:
                stage = destination.create_stage(stage_name)
                stage.open()
            except Exception as exc:
                logger.warning(
                    "Failed to create/open streaming tool stage (index %s): %s",
                    index,
                    exc,
                    exc_info=True,
                )
                return
            state = _StreamingToolStageState(
                stage=stage,
                start_time=perf_counter(),
                name_set=function_name is not None,
            )
            if function_name:
                state.function_name = function_name
                self._ensure_presenter(state)
            self._tool_stages_by_index[index] = state

        if not state.name_set and tool_call.function and tool_call.function.name:
            function_name = tool_call.function.name
            if function_name in self._suppressed_tool_stage_names:
                self._suppressed_tool_indexes.add(index)
                try:
                    state.stage.close(status=Status.COMPLETED)
                except Exception as exc:
                    logger.warning(
                        "Failed to close suppressed streaming tool stage (index %s): %s",
                        index,
                        exc,
                        exc_info=True,
                    )
                self._tool_stages_by_index.pop(index, None)
                return
            display_name = self._tool_stage_display_names.get(
                function_name, f"Calling {function_name}"
            )
            try:
                state.stage.append_name(display_name)
                state.name_set = True
            except Exception as exc:
                logger.warning(
                    "Failed to append name to streaming tool stage (index %s): %s",
                    index,
                    exc,
                )
            state.function_name = function_name
            self._ensure_presenter(state)

        arguments_chunk = tool_call.function.arguments if tool_call.function else None
        if not arguments_chunk:
            return
        self._feed_argument_chunk(state, index, arguments_chunk)

    def _ensure_presenter(self, state: _StreamingToolStageState) -> None:
        if state.presenter is not None or not state.function_name:
            return
        presentation = self._argument_stream_presentations.get(state.function_name)
        if presentation is None:
            state.pending_argument_chunks.clear()
            return
        state.presenter = StreamingArgumentPresenter(state.stage.append_content, presentation)
        for buffered in state.pending_argument_chunks:
            state.presenter.feed(buffered)
        state.pending_argument_chunks.clear()

    @staticmethod
    def _feed_argument_chunk(
        state: _StreamingToolStageState, index: int, arguments_chunk: str
    ) -> None:
        if state.presenter is None:
            if state.function_name is None:
                state.pending_argument_chunks.append(arguments_chunk)
            return
        try:
            state.presenter.feed(arguments_chunk)
        except Exception as exc:
            raise ChatStreamWriteError(
                f"Failed to append tool-call arguments to streaming stage (index {index})."
            ) from exc

    def _publish_adopted_tool_stages(self) -> None:
        for index, state in list(self._tool_stages_by_index.items()):
            tool_call = self._accumulator.get_tool_call_at_index(index)
            tool_call_id = tool_call.id_or_none if tool_call is not None else None
            if tool_call_id is None:
                logger.warning(
                    "Closing streaming tool stage without tool_call id (index=%s)", index
                )
                try:
                    state.stage.close(status=Status.COMPLETED)
                except Exception as exc:
                    logger.warning(
                        "Failed to close streaming tool stage without id (index %s): %s",
                        index,
                        exc,
                        exc_info=True,
                    )
                self._tool_stages_by_index.pop(index, None)
                continue
            if state.presenter is not None:
                try:
                    state.presenter.finish()
                except Exception as exc:
                    logger.warning(
                        "Failed to finish streaming argument presenter (index %s): %s",
                        index,
                        exc,
                    )
            request_body_streamed = bool(
                state.presenter is not None and state.presenter.request_body_streamed
            )
            self._accumulator.set_adopted_tool_stage(
                tool_call_id,
                AdoptedToolStage(
                    stage=state.stage,
                    start_time=state.start_time,
                    request_body_streamed=request_body_streamed,
                ),
            )
            self._tool_stages_by_index.pop(index, None)

    def _stream_stage_delta(self, delta: StageDeltaItem, position: int) -> None:
        destination = self._destination
        assert destination is not None

        idx = get_stage_index(delta, position)
        stage_name = stage_display_name(delta)

        stage = self._stages_by_index.get(idx)
        just_created = False
        if stage is None:
            if not stage_name:
                logger.warning(
                    "Skipping stage delta propagation because stage name is missing (index=%s)",
                    idx,
                )
                log_payload(logger, "Stage delta with missing name: %s", delta)
                return
            try:
                stage = destination.create_stage(stage_name)
                stage.open()
                self._stages_by_index[idx] = stage
                just_created = True
            except Exception as exc:
                logger.warning(
                    "Failed to create/open orchestrator stage '%s' (index %s): %s",
                    stage_name,
                    idx,
                    exc,
                    exc_info=True,
                )
                return

        if not just_created and "name" in delta and delta["name"] is not None:
            try:
                stage.append_name(str(delta["name"]))
            except Exception as exc:
                logger.warning(
                    "Failed to append name to streaming stage (index %s): %s",
                    idx,
                    exc,
                )

        if "content" in delta and delta["content"]:
            try:
                stage.append_content(str(delta["content"]))
            except Exception as exc:  # pragma: no cover - defensive
                label = stage_name or f"index {idx}"
                raise ChatStreamWriteError(f"Failed to append content to stage '{label}'.") from exc

        if "attachments" in delta and delta["attachments"]:
            for att in delta["attachments"]:
                if isinstance(att, dict):
                    try:
                        stage.add_attachment(**attachment_kwargs(att))
                    except Exception as exc:
                        logger.warning(
                            "Failed to add attachment to streaming stage (index %s): %s",
                            idx,
                            exc,
                        )

        if "status" in delta and delta["status"] is not None:
            status = (
                Status.COMPLETED
                if str(delta["status"]).lower() == Status.COMPLETED.value
                else Status.FAILED
            )
            self._close_streaming_stage_at_index(self._stages_by_index, idx, status)

    @staticmethod
    def _close_streaming_stage_at_index(
        stages_by_index: dict[int, Stage], idx: int, status: Status
    ) -> None:
        stage = stages_by_index.pop(idx, None)
        if stage is None:
            return
        try:
            stage.close(status=status)
        except Exception as exc:
            logger.warning(
                "Error closing orchestrator streaming stage (index %s): %s",
                idx,
                exc,
                exc_info=True,
            )

    def _close_all_streaming_stages(self, status: Status) -> None:
        for idx in list(self._stages_by_index.keys()):
            self._close_streaming_stage_at_index(self._stages_by_index, idx, status)

    def _close_all_tool_stages(self, status: Status) -> None:
        for idx in list(self._tool_stages_by_index.keys()):
            state = self._tool_stages_by_index.pop(idx, None)
            if state is None:
                continue
            try:
                state.stage.close(status=status)
            except Exception as exc:
                logger.warning(
                    "Error closing streaming tool stage (index %s): %s",
                    idx,
                    exc,
                    exc_info=True,
                )
