import logging
from collections.abc import AsyncIterable
from time import perf_counter

from aidial_sdk.chat_completion import Choice, Stage, Status
from openai import APIError, BadRequestError
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from pydantic import BaseModel, ConfigDict

from quickapp.common._stage_delta_types import (
    StageDeltaItem,
    as_stage_delta,
    attachment_kwargs,
    get_stage_index,
    stage_display_name,
)
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.adopted_tool_stage import AdoptedToolStage
from quickapp.common.chat_completion_stream.argument_stream_presentation import (
    ArgumentStreamPresentation,
    StreamingArgumentPresenter,
)
from quickapp.common.chat_completion_stream.driver import iter_chat_completion_events
from quickapp.common.chat_completion_stream.exceptions import (
    ChatStreamHandlerError,
    ChatStreamParseError,
    ChatStreamWriteError,
)
from quickapp.common.chat_completion_stream.models import (
    ChatStreamEvent,
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    NormalizedCustomContent,
)
from quickapp.common.chat_completion_stream.parse import parse_chat_completion_chunk
from quickapp.common.chat_completion_stream.stream_result import (
    ChatStreamAccumulator,
    ensure_attachment_url_or_data,
)
from quickapp.common.payload_logging import log_payload

logger = logging.getLogger(__name__)


class _StreamingToolStageState:
    """Mutable UI state for a tool-call stage opened while arguments are still streaming."""

    __slots__ = (
        "stage",
        "start_time",
        "name_set",
        "function_name",
        "presenter",
        "pending_argument_chunks",
    )

    def __init__(self, stage: Stage, start_time: float, *, name_set: bool) -> None:
        self.stage = stage
        self.start_time = start_time
        self.name_set = name_set
        self.function_name: str | None = None
        self.presenter: StreamingArgumentPresenter | None = None
        self.pending_argument_chunks: list[str] = []


class ChatStreamConfig(BaseModel):
    """Orchestrator: set ``destination`` (+ ``propagate_stages``). Deployment: set ``stage_wrapper``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    destination: Choice | None = None
    stage_wrapper: BaseStageWrapper | None = None
    stream_content: bool = True
    propagate_stages: bool = False
    argument_stream_presentations: dict[str, ArgumentStreamPresentation] = {}


class ChatCompletionStreamHandler:
    async def process_stream(
        self,
        *,
        chunks: AsyncIterable[ChatCompletionChunk],
        config: ChatStreamConfig,
    ) -> ChatStreamAccumulator:
        accumulator = ChatStreamAccumulator()
        if config.stage_wrapper:
            config.stage_wrapper.append_stage_content("> #### Response:\n")
        elif config.destination is not None:
            config.destination.append_content("\n\r")
        await self._run(chat_completion=chunks, accumulator=accumulator, config=config)
        self._log_stream_accumulator(accumulator)
        return accumulator

    async def _run(
        self,
        *,
        chat_completion: AsyncIterable[ChatCompletionChunk],
        accumulator: ChatStreamAccumulator,
        config: ChatStreamConfig,
    ) -> None:
        stages_by_index: dict[int, Stage] = {}
        tool_stages_by_index: dict[int, _StreamingToolStageState] = {}
        succeeded = False

        try:
            async for event in iter_chat_completion_events(
                chat_completion,
                parse_chat_completion_chunk,
            ):
                self._apply_stream_event(
                    accumulator, config, stages_by_index, tool_stages_by_index, event
                )
            succeeded = True
            self._publish_adopted_tool_stages(accumulator, tool_stages_by_index)
        except (BadRequestError, APIError, ChatStreamHandlerError):
            raise
        except Exception as exc:
            raise ChatStreamParseError("Failed to consume/parse chat completion stream.") from exc
        finally:
            leftover_status = Status.COMPLETED if succeeded else Status.FAILED
            self._close_all_streaming_stages(stages_by_index, leftover_status)
            if not succeeded:
                self._close_all_tool_stages(tool_stages_by_index, Status.FAILED)

    def _apply_stream_event(
        self,
        accumulator: ChatStreamAccumulator,
        config: ChatStreamConfig,
        stages_by_index: dict[int, Stage],
        tool_stages_by_index: dict[int, _StreamingToolStageState],
        event: ChatStreamEvent,
    ) -> None:
        if isinstance(event, ChunkUsageFootprint):
            accumulator.apply_usage_footprint(event)
        elif isinstance(event, NormalizedChoiceDelta):
            self._handle_delta(accumulator, config, stages_by_index, tool_stages_by_index, event)
        else:
            logger.warning("Unexpected event of type %s", type(event))

    def _handle_delta(
        self,
        accumulator: ChatStreamAccumulator,
        config: ChatStreamConfig,
        stages_by_index: dict[int, Stage],
        tool_stages_by_index: dict[int, _StreamingToolStageState],
        delta: NormalizedChoiceDelta,
    ) -> None:
        # Apply reasoning/model stages first so a chunk can finish stage content
        # before a phase transition closes them.
        if delta.custom is not None:
            self._apply_custom(accumulator, config, stages_by_index, delta.custom)

        leaving_reasoning = bool(delta.tool_calls) or bool(delta.content and config.stream_content)
        if leaving_reasoning and stages_by_index:
            self._close_all_streaming_stages(stages_by_index, Status.COMPLETED)

        if delta.content and config.stream_content:
            dest = config.destination
            wrap = config.stage_wrapper
            try:
                if dest is not None:
                    dest.append_content(delta.content)
                elif wrap is not None:
                    wrap.append_stage_content(delta.content)
            except Exception as exc:  # pragma: no cover - defensive
                raise ChatStreamWriteError("Failed to stream content to destination") from exc
            accumulator.append_content(delta.content)

        for tool_call in delta.tool_calls:
            accumulator.append_tool_call_delta(tool_call)
            if config.destination is not None:
                self._stream_tool_call_delta(config, accumulator, tool_stages_by_index, tool_call)

    def _stream_tool_call_delta(
        self,
        config: ChatStreamConfig,
        accumulator: ChatStreamAccumulator,
        tool_stages_by_index: dict[int, _StreamingToolStageState],
        tool_call: ChoiceDeltaToolCall,
    ) -> None:
        destination = config.destination
        if destination is None:
            return

        index = tool_call.index
        state = tool_stages_by_index.get(index)
        if state is None:
            function_name = None
            if tool_call.function and tool_call.function.name:
                function_name = tool_call.function.name
            # Open immediately (even before the function name arrives) so the UI
            # shows progress while large argument payloads stream in.
            stage_name = f"Calling {function_name}" if function_name else None
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
                self._ensure_presenter(state, config)
            tool_stages_by_index[index] = state

        if not state.name_set and tool_call.function and tool_call.function.name:
            try:
                state.stage.append_name(f"Calling {tool_call.function.name}")
                state.name_set = True
            except Exception as exc:
                logger.warning(
                    "Failed to append name to streaming tool stage (index %s): %s",
                    index,
                    exc,
                )
            state.function_name = tool_call.function.name
            self._ensure_presenter(state, config)

        arguments_chunk = tool_call.function.arguments if tool_call.function else None
        if not arguments_chunk:
            return

        self._feed_argument_chunk(state, index, arguments_chunk)

    @staticmethod
    def _ensure_presenter(state: _StreamingToolStageState, config: ChatStreamConfig) -> None:
        if state.presenter is not None or not state.function_name:
            return
        presentation = config.argument_stream_presentations.get(state.function_name)
        if presentation is None:
            # Tool opted out / unknown — drop any buffered chunks (static add_parameters later).
            state.pending_argument_chunks.clear()
            return
        state.presenter = StreamingArgumentPresenter(state.stage.append_content, presentation)
        for buffered in state.pending_argument_chunks:
            state.presenter.feed(buffered)
        state.pending_argument_chunks.clear()

    def _feed_argument_chunk(
        self, state: _StreamingToolStageState, index: int, arguments_chunk: str
    ) -> None:
        if state.presenter is None:
            if state.function_name is None:
                # Name not known yet — buffer until presentation can be selected.
                state.pending_argument_chunks.append(arguments_chunk)
            return
        try:
            state.presenter.feed(arguments_chunk)
        except Exception as exc:
            raise ChatStreamWriteError(
                f"Failed to append tool-call arguments to streaming stage (index {index})."
            ) from exc

    @staticmethod
    def _publish_adopted_tool_stages(
        accumulator: ChatStreamAccumulator,
        tool_stages_by_index: dict[int, _StreamingToolStageState],
    ) -> None:
        for index, state in list(tool_stages_by_index.items()):
            tool_call = accumulator.get_tool_call_at_index(index)
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
                tool_stages_by_index.pop(index, None)
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
            streamed_names = (
                state.presenter.streamed_parameter_names
                if state.presenter is not None
                else frozenset()
            )
            request_body_streamed = bool(
                state.presenter is not None and state.presenter.request_body_streamed
            )
            accumulator.set_adopted_tool_stage(
                tool_call_id,
                AdoptedToolStage(
                    stage=state.stage,
                    start_time=state.start_time,
                    streamed_parameter_names=streamed_names,
                    request_body_streamed=request_body_streamed,
                ),
            )
            tool_stages_by_index.pop(index, None)

    def _process_attachments_to_destination(self, attachments: list, destination) -> None:
        """Process attachments: extend accumulator, ensure URL/data, and add to destination."""
        if not attachments:
            return
        for attachment in attachments:
            ensure_attachment_url_or_data(attachment)
            try:
                destination.add_attachment(attachment)
            except Exception as exc:
                raise ChatStreamWriteError("Failed to stream attachment.") from exc

    def _apply_custom(
        self,
        accumulator: ChatStreamAccumulator,
        config: ChatStreamConfig,
        stages_by_index: dict[int, Stage],
        norm: NormalizedCustomContent,
    ) -> None:
        dest = config.destination
        wrap = config.stage_wrapper

        if dest is not None and norm.attachments:
            self._process_attachments_to_destination(norm.attachments, dest)
        elif wrap is not None and norm.attachments:
            self._process_attachments_to_destination(norm.attachments, wrap)
        accumulator.extend_attachments(norm.attachments)

        for position, raw in norm.stage_entries:
            stage_delta = as_stage_delta(raw)
            accumulator.append_stage_delta(stage_delta, position)
            if config.propagate_stages and dest is not None:
                self._stream_stage_delta(config, stages_by_index, stage_delta, position)

        if norm.state is not None:
            accumulator.merge_state(norm.state)

    def _stream_stage_delta(
        self,
        config: ChatStreamConfig,
        stages_by_index: dict[int, Stage],
        delta: StageDeltaItem,
        position: int,
    ) -> None:
        dest = config.destination
        if dest is None:
            return

        idx = get_stage_index(delta, position)
        stage_name = stage_display_name(delta)

        stage = stages_by_index.get(idx)
        just_created = False
        if stage is None:
            if not stage_name:
                logger.warning(
                    "Skipping stage delta propagation because stage name is missing (index=%s)", idx
                )
                log_payload(logger, "Stage delta with missing name: %s", delta)
                return
            try:
                stage = dest.create_stage(stage_name)
                stage.open()
                stages_by_index[idx] = stage
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
            self._close_streaming_stage_at_index(stages_by_index, idx, status)

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

    def _close_all_streaming_stages(
        self, stages_by_index: dict[int, Stage], status: Status
    ) -> None:
        for idx in list(stages_by_index.keys()):
            self._close_streaming_stage_at_index(stages_by_index, idx, status)

    @staticmethod
    def _close_all_tool_stages(
        tool_stages_by_index: dict[int, _StreamingToolStageState], status: Status
    ) -> None:
        for idx in list(tool_stages_by_index.keys()):
            state = tool_stages_by_index.pop(idx, None)
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

    @staticmethod
    def _log_stream_accumulator(result: ChatStreamAccumulator) -> None:
        tool_calls = result.tool_calls  # property rebuilds a list on each access
        logger.debug(
            "LLM response accumulated: content_length=%d, tool_calls=%s, attachments=%d, "
            "stages=%d, state_keys=%s, usage=%s",
            len(result.content),
            [tool.name for tool in tool_calls] if tool_calls else [],
            len(result.attachments),
            len(result.stages),
            list(result.state) if result.state else [],
            (
                f"{result.usage.prompt_tokens}/{result.usage.completion_tokens}"
                if result.usage
                else None
            ),
        )
        if result.content:
            log_payload(logger, "LLM response content: %s", result.content)
        for tool in tool_calls or []:
            log_payload(logger, "LLM tool call args (%s): %s", tool.name, tool.arguments)
        if result.attachments:
            log_payload(logger, "LLM response attachments: %s", result.attachments)
        if result.stages:
            log_payload(logger, "LLM response stages: %s", result.stages)
        if result.state:
            log_payload(logger, "LLM response state: %s", result.state)
