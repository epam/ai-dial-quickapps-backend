from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from typing import Annotated

from aidial_sdk.chat_completion import Choice, Stage, Status
from openai.types.chat import ChatCompletionChunk
from pydantic import BaseModel, ConfigDict, SkipValidation

from quickapp.agent._stage_delta_types import (
    StageDeltaItem,
    as_stage_delta,
    attachment_kwargs,
    get_stage_index,
    stage_display_name,
)
from quickapp.common.base_stage_wrapper import BaseStageWrapper
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
    attachment_to_sdk,
    fix_sdk_attachment,
)

logger = logging.getLogger(__name__)


class ChatStreamConfig(BaseModel):
    """Orchestrator: set ``destination`` (+ ``propagate_stages``). Deployment: set ``stage_wrapper``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # SkipValidation: SDK types are not validated as subclasses (tests use Mock).
    destination: Annotated[Choice | None, SkipValidation()] = None
    stage_wrapper: Annotated[BaseStageWrapper | None, SkipValidation()] = None
    stream_content: bool = True
    propagate_stages: bool = False


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

        try:
            async for event in iter_chat_completion_events(
                chat_completion,
                parse_chat_completion_chunk,
            ):
                self._apply_stream_event(accumulator, config, stages_by_index, event)
        except ChatStreamHandlerError:
            self._close_all_streaming_stages(stages_by_index, Status.FAILED)
            raise
        except Exception as exc:
            self._close_all_streaming_stages(stages_by_index, Status.FAILED)
            raise ChatStreamParseError("Failed to consume/parse chat completion stream.") from exc
        self._finalize_remaining_streaming_stages(stages_by_index)

    def _finalize_remaining_streaming_stages(self, stages_by_index: dict[int, Stage]) -> None:
        self._close_all_streaming_stages(stages_by_index, Status.FAILED)

    def _apply_stream_event(
        self,
        accumulator: ChatStreamAccumulator,
        config: ChatStreamConfig,
        stages_by_index: dict[int, Stage],
        event: ChatStreamEvent,
    ) -> None:
        if isinstance(event, ChunkUsageFootprint):
            accumulator.apply_usage_footprint(event)
        elif isinstance(event, NormalizedChoiceDelta):
            self._handle_delta(accumulator, config, stages_by_index, event)

    def _handle_delta(
        self,
        accumulator: ChatStreamAccumulator,
        config: ChatStreamConfig,
        stages_by_index: dict[int, Stage],
        delta: NormalizedChoiceDelta,
    ) -> None:
        if delta.content and config.stream_content:
            dest = config.destination
            wrap = config.stage_wrapper
            if dest is not None:
                try:
                    dest.append_content(delta.content)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ChatStreamWriteError("Failed to stream content to choice sink.") from exc
            elif wrap is not None:
                try:
                    wrap.append_stage_content(delta.content)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ChatStreamWriteError(
                        "Failed to stream content to deployment stage wrapper."
                    ) from exc
            accumulator.append_content(delta.content)

        if delta.custom is not None:
            self._apply_custom(accumulator, config, stages_by_index, delta.custom)

        for tool_call in delta.tool_calls:
            accumulator.append_tool_call_delta(tool_call)

    def _apply_custom(
        self,
        accumulator: ChatStreamAccumulator,
        config: ChatStreamConfig,
        stages_by_index: dict[int, Stage],
        norm: NormalizedCustomContent,
    ) -> None:
        dest = config.destination
        wrap = config.stage_wrapper

        if dest is not None:
            for attachment in norm.sdk_attachments:
                fix_sdk_attachment(attachment)
                try:
                    dest.add_attachment(**attachment.model_dump())
                except Exception as exc:  # pragma: no cover - defensive
                    raise ChatStreamWriteError(
                        "Failed to stream attachment to choice sink."
                    ) from exc
                accumulator.append_attachment(attachment)
        elif wrap is not None and norm.sdk_attachments:
            accumulator.extend_attachments_from_api(norm.sdk_attachments)
            for attachment in norm.sdk_attachments:
                fix_sdk_attachment(attachment)
                try:
                    wrap.add_attachment(attachment_to_sdk(attachment))
                except Exception as exc:  # pragma: no cover - defensive
                    raise ChatStreamWriteError(
                        "Failed to stream attachment to deployment stage wrapper."
                    ) from exc
        elif norm.sdk_attachments:
            accumulator.extend_attachments_from_api(norm.sdk_attachments)

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
                    "Skipping stage delta propagation because stage name is missing: %s", delta
                )
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
    def _log_stream_accumulator(result: ChatStreamAccumulator) -> None:
        logger.debug("===================")
        logger.debug(" ---- Captured values:")
        logger.debug(" ----- text llm response: %s", result.content)
        if result.tool_calls:
            logger.debug(" ------ tool_calls:")
            for tool in result.tool_calls:
                logger.debug(" -------- %s - %s - %s", tool.name, tool.arguments, tool)
        if result.attachments:
            logger.debug(" ------ attachments: %s", result.attachments)
        if result.stages:
            logger.debug(" ------ stages: %s", result.stages)
        if result.state:
            logger.debug(" ------ state: %s", result.state)
        if result.usage:
            logger.debug(
                " ------ usage: prompt_tokens=%s completion_tokens=%s",
                result.usage.prompt_tokens,
                result.usage.completion_tokens,
            )
        logger.debug("===================")
