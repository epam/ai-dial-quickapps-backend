from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from typing import Protocol

from aidial_sdk.chat_completion import Choice, Stage, Status
from openai.types.chat import ChatCompletionChunk
from pydantic import BaseModel, ConfigDict

from quickapp.agent._stage_delta_types import (
    StageDeltaItem,
    as_stage_delta,
    attachment_kwargs,
    get_stage_index,
    stage_display_name,
)
from quickapp.common.chat_completion_stream.driver import consume_chat_completion_chunks
from quickapp.common.chat_completion_stream.exceptions import (
    ChatStreamHandlerError,
    ChatStreamInvariantError,
    ChatStreamParseError,
    ChatStreamSinkWriteError,
)
from quickapp.common.chat_completion_stream.models import (
    ChatStreamEvent,
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    NormalizedCustomContent,
)
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.parse import parse_chat_completion_chunk
from quickapp.common.chat_completion_stream.stream_result import (
    ChatStreamAccumulator,
    attachment_to_sdk,
    fix_sdk_attachment,
)

logger = logging.getLogger(__name__)


class _StreamStrategy(Protocol):
    def handle_footprint(self, fp: ChunkUsageFootprint) -> None: ...

    def handle_delta(self, delta: NormalizedChoiceDelta) -> None: ...

    def finalize(self) -> None: ...


class ChatStreamStrategyConfig(BaseModel):
    """Single strategy: orchestrator sets ``destination`` (+ ``propagate_stages``); deployment sets ``stage_wrapper``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    destination: Choice | None = None
    stage_wrapper: BaseStageWrapper | None = None
    stream_content: bool = True
    propagate_stages: bool = False


class _ChatStreamStrategy:
    def __init__(self, *, accumulator: ChatStreamAccumulator, config: ChatStreamStrategyConfig) -> None:
        self._accumulator = accumulator
        self._config = config
        self._stages_by_index: dict[int, Stage] = {}

    def handle_footprint(self, fp: ChunkUsageFootprint) -> None:
        self._accumulator.apply_usage_footprint(fp)

    def handle_delta(self, delta: NormalizedChoiceDelta) -> None:
        if delta.content and self._config.stream_content:
            dest = self._config.destination
            wrap = self._config.stage_wrapper
            if dest is not None:
                try:
                    dest.append_content(delta.content)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ChatStreamSinkWriteError(
                        "Failed to stream content to choice sink."
                    ) from exc
            elif wrap is not None:
                try:
                    wrap.append_stage_content(delta.content)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ChatStreamSinkWriteError(
                        "Failed to stream content to deployment stage wrapper."
                    ) from exc
            self._accumulator.append_content(delta.content)

        if delta.custom is not None:
            self._apply_custom(delta.custom)

        for tool_call in delta.tool_calls:
            self._accumulator.append_tool_call_delta(tool_call)

    def finalize(self) -> None:
        self._close_all_streaming_stages(status=Status.FAILED)

    def _apply_custom(self, norm: NormalizedCustomContent) -> None:
        dest = self._config.destination
        wrap = self._config.stage_wrapper

        if dest is not None:
            for attachment in norm.sdk_attachments:
                fix_sdk_attachment(attachment)
                try:
                    dest.add_attachment(**attachment.model_dump())
                except Exception as exc:  # pragma: no cover - defensive
                    raise ChatStreamSinkWriteError(
                        "Failed to stream attachment to choice sink."
                    ) from exc
                self._accumulator.append_attachment(attachment)
        elif wrap is not None and norm.sdk_attachments:
            self._accumulator.extend_attachments_from_api(norm.sdk_attachments)
            for attachment in norm.sdk_attachments:
                fix_sdk_attachment(attachment)
                try:
                    wrap.add_attachment(attachment_to_sdk(attachment))
                except Exception as exc:  # pragma: no cover - defensive
                    raise ChatStreamSinkWriteError(
                        "Failed to stream attachment to deployment stage wrapper."
                    ) from exc
        elif norm.sdk_attachments:
            self._accumulator.extend_attachments_from_api(norm.sdk_attachments)

        for position, raw in norm.stage_entries:
            delta = as_stage_delta(raw)
            self._accumulator.append_stage_delta(delta, position)
            if self._config.propagate_stages and dest is not None:
                self._stream_stage_delta(delta, position)

        if norm.state is not None:
            self._accumulator.merge_state(norm.state)

    def _stream_stage_delta(self, delta: StageDeltaItem, position: int) -> None:
        dest = self._config.destination
        if dest is None:
            return

        idx = get_stage_index(delta, position)
        stage_name = stage_display_name(delta)

        stage = self._stages_by_index.get(idx)
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
                raise ChatStreamSinkWriteError(
                    f"Failed to append content to stage '{label}'."
                ) from exc

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
            self._close_streaming_stage_at_index(idx, status)

    def _close_streaming_stage_at_index(self, idx: int, status: Status) -> None:
        stage = self._stages_by_index.pop(idx, None)
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
            self._close_streaming_stage_at_index(idx, status)


class ChatStreamEventDispatcher:
    def __init__(self, *, strategy: _StreamStrategy) -> None:
        self._strategy = strategy

    def __call__(self, event: ChatStreamEvent) -> None:
        if isinstance(event, ChunkUsageFootprint):
            self._strategy.handle_footprint(event)
            return
        self._strategy.handle_delta(event)


class ChatCompletionStreamHandler:
    async def process_orchestrator_stream(
        self,
        *,
        chat_completion: AsyncIterable[ChatCompletionChunk],
        config: ChatStreamStrategyConfig,
    ) -> ChatStreamAccumulator:
        accumulator = ChatStreamAccumulator()
        # Preserve existing behavior for orchestrator responses.
        if config.destination is not None:
            config.destination.append_content("\n\r")
        strategy = _ChatStreamStrategy(accumulator=accumulator, config=config)
        await self._run(chat_completion=chat_completion, strategy=strategy)
        self._log_stream_accumulator(accumulator)
        return accumulator

    async def process_deployment_stream(
        self,
        *,
        chunks: AsyncIterable[ChatCompletionChunk],
        config: ChatStreamStrategyConfig,
    ) -> ChatStreamAccumulator:
        accumulator = ChatStreamAccumulator()
        if config.stage_wrapper:
            config.stage_wrapper.append_stage_content("> #### Response:\n")
        strategy = _ChatStreamStrategy(accumulator=accumulator, config=config)
        await self._run(chat_completion=chunks, strategy=strategy)
        return accumulator

    async def _run(
        self,
        *,
        chat_completion: AsyncIterable[ChatCompletionChunk],
        strategy: _StreamStrategy,
    ) -> None:
        dispatcher = ChatStreamEventDispatcher(strategy=strategy)
        try:
            await consume_chat_completion_chunks(
                chat_completion,
                parse_chat_completion_chunk,
                dispatcher,
            )
        except ChatStreamHandlerError:
            strategy.finalize()
            raise
        except Exception as exc:
            strategy.finalize()
            raise ChatStreamParseError("Failed to consume/parse chat completion stream.") from exc

        try:
            strategy.finalize()
        except ChatStreamHandlerError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise ChatStreamInvariantError("Stream strategy finalization failed.") from exc

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
