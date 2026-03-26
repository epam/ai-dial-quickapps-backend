from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from functools import partial
from typing import Any, Protocol

from aidial_sdk.chat_completion import Stage, Status
from openai.types.chat import ChatCompletionChunk
from pydantic import BaseModel, ConfigDict

from quickapp.agent._stage_delta_types import (
    StageDeltaItem,
    as_stage_delta,
    attachment_kwargs,
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
    ChatStreamFootprintMode,
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    NormalizedCustomContent,
)
from quickapp.common.chat_completion_stream.parse import parse_chat_completion_chunk
from quickapp.common.chat_completion_stream.stream_result import (
    ChatStreamAccumulator,
    attachment_to_sdk,
)

logger = logging.getLogger(__name__)


class _StreamStrategy(Protocol):
    def handle_footprint(self, fp: ChunkUsageFootprint) -> None: ...

    def handle_delta(self, delta: NormalizedChoiceDelta) -> None: ...

    def finalize(self) -> None: ...


class OrchestratorStreamStrategyConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    destination: Any
    stream_content: bool = True
    propagate_orchestrator_stages: bool = True


class DeploymentStreamStrategyConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    stage_wrapper: Any | None = None


class _OrchestratorStreamStrategy:
    def __init__(
        self, *, accumulator: ChatStreamAccumulator, config: OrchestratorStreamStrategyConfig
    ) -> None:
        self._accumulator = accumulator
        self._config = config
        self._streaming_stages: dict[str, Stage] = {}
        self._stage_names_by_index: dict[int, str] = {}

    def handle_footprint(self, fp: ChunkUsageFootprint) -> None:
        self._accumulator.apply_usage_footprint(fp, mode=ChatStreamFootprintMode.ORCHESTRATOR)

    def handle_delta(self, delta: NormalizedChoiceDelta) -> None:
        if delta.content and self._config.stream_content:
            self._append_choice_content(delta.content)
            self._accumulator.append_content(delta.content)

        if delta.custom is not None:
            self._apply_custom(delta.custom)

        for tool_call in delta.tool_calls:
            self._accumulator.append_tool_call_delta(tool_call)

    def finalize(self) -> None:
        self._close_all_streaming_stages(status=Status.FAILED)

    @staticmethod
    def _fix_attachment(attachment: Any) -> None:
        if attachment.data is None and attachment.url is None:
            if attachment.reference_url is None:
                attachment["data"] = ""
            else:
                attachment.url = attachment.reference_url

    def _append_choice_content(self, content: str) -> None:
        try:
            self._config.destination.append_content(content)
        except Exception as exc:  # pragma: no cover - defensive
            raise ChatStreamSinkWriteError("Failed to stream content to choice sink.") from exc

    def _apply_custom(self, norm: NormalizedCustomContent) -> None:
        for attachment in norm.sdk_attachments:
            self._fix_attachment(attachment)
            try:
                self._config.destination.add_attachment(**attachment.model_dump())
            except Exception as exc:  # pragma: no cover - defensive
                raise ChatStreamSinkWriteError(
                    "Failed to stream attachment to choice sink."
                ) from exc
            self._accumulator.append_attachment(attachment)

        for position, raw in norm.stage_entries:
            delta = as_stage_delta(raw)
            self._accumulator.append_stage_delta(delta, position)
            if self._config.propagate_orchestrator_stages:
                self._stream_stage_delta(delta, position)

        if norm.state is not None:
            self._accumulator.merge_state(norm.state)

    def _stream_stage_delta(self, delta: StageDeltaItem, position: int) -> None:
        stage_index = delta.get("index") if isinstance(delta.get("index"), int) else None
        stage_name = stage_display_name(delta)
        if stage_name and stage_index is not None:
            self._stage_names_by_index[stage_index] = stage_name
        elif stage_name is None and stage_index is not None:
            stage_name = self._stage_names_by_index.get(stage_index)
        if not stage_name:
            logger.warning(
                "Skipping stage delta propagation because stage name is missing: %s", delta
            )
            return

        stage = self._streaming_stages.get(stage_name)
        if stage is None:
            try:
                stage = self._config.destination.create_stage(stage_name)
                stage.open()
                self._streaming_stages[stage_name] = stage
            except Exception as exc:
                logger.warning(
                    "Failed to create/open orchestrator stage '%s': %s",
                    stage_name,
                    exc,
                    exc_info=True,
                )
                return

        if "content" in delta and delta["content"]:
            try:
                stage.append_content(str(delta["content"]))
            except Exception as exc:  # pragma: no cover - defensive
                raise ChatStreamSinkWriteError(
                    f"Failed to append content to stage '{stage_name}'."
                ) from exc

        if "attachments" in delta and delta["attachments"]:
            for att in delta["attachments"]:
                if isinstance(att, dict):
                    try:
                        stage.add_attachment(**attachment_kwargs(att))
                    except Exception as exc:
                        logger.warning(
                            "Failed to add attachment to stage '%s': %s",
                            stage_name,
                            exc,
                        )

        if "status" in delta and delta["status"] is not None:
            status = (
                Status.COMPLETED
                if str(delta["status"]).lower() == Status.COMPLETED.value
                else Status.FAILED
            )
            self._close_streaming_stage(stage_name, status)
            if stage_index is not None:
                self._stage_names_by_index.pop(stage_index, None)

    def _close_streaming_stage(self, stage_name: str, status: Status) -> None:
        stage = self._streaming_stages.pop(stage_name, None)
        if stage is None:
            return
        try:
            stage.close(status=status)
        except Exception as exc:
            logger.warning(
                "Error closing orchestrator stage '%s': %s",
                stage_name,
                exc,
                exc_info=True,
            )

    def _close_all_streaming_stages(self, status: Status) -> None:
        for stage_name in list(self._streaming_stages.keys()):
            self._close_streaming_stage(stage_name, status)


class _DeploymentStreamStrategy:
    def __init__(
        self, *, accumulator: ChatStreamAccumulator, config: DeploymentStreamStrategyConfig
    ) -> None:
        self._accumulator = accumulator
        self._config = config

    def handle_footprint(self, fp: ChunkUsageFootprint) -> None:
        self._accumulator.apply_usage_footprint(fp, mode=ChatStreamFootprintMode.DEPLOYMENT)

    def handle_delta(self, delta: NormalizedChoiceDelta) -> None:
        if delta.content:
            if self._config.stage_wrapper is not None:
                try:
                    self._config.stage_wrapper.append_stage_content(delta.content)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ChatStreamSinkWriteError(
                        "Failed to stream content to deployment stage wrapper."
                    ) from exc
            self._accumulator.append_content(delta.content)

        if delta.custom is not None:
            self._apply_custom(delta.custom)

    def finalize(self) -> None:
        return

    @staticmethod
    def _fix_attachment(attachment: Any) -> None:
        if attachment.data is None and attachment.url is None:
            if attachment.reference_url is None:
                attachment["data"] = ""
            else:
                attachment.url = attachment.reference_url

    def _apply_custom(self, norm: NormalizedCustomContent) -> None:
        if norm.sdk_attachments:
            self._accumulator.extend_attachments_from_api(norm.sdk_attachments)
            if self._config.stage_wrapper is not None:
                for attachment in norm.sdk_attachments:
                    self._fix_attachment(attachment)
                    try:
                        self._config.stage_wrapper.add_attachment(attachment_to_sdk(attachment))
                    except Exception as exc:  # pragma: no cover - defensive
                        raise ChatStreamSinkWriteError(
                            "Failed to stream attachment to deployment stage wrapper."
                        ) from exc
        if norm.state is not None:
            self._accumulator.merge_state(norm.state)


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
        config: OrchestratorStreamStrategyConfig,
    ) -> ChatStreamAccumulator:
        accumulator = ChatStreamAccumulator()
        # Preserve existing behavior for orchestrator responses.
        config.destination.append_content("\n\r")
        strategy = _OrchestratorStreamStrategy(accumulator=accumulator, config=config)
        await self._run(
            chat_completion=chat_completion,
            mode=ChatStreamFootprintMode.ORCHESTRATOR,
            strategy=strategy,
        )
        self._log_stream_accumulator(accumulator)
        return accumulator

    async def process_deployment_stream(
        self,
        *,
        chunks: AsyncIterable[ChatCompletionChunk],
        config: DeploymentStreamStrategyConfig,
    ) -> ChatStreamAccumulator:
        accumulator = ChatStreamAccumulator()
        if config.stage_wrapper:
            config.stage_wrapper.append_stage_content("> #### Response:\n")
        strategy = _DeploymentStreamStrategy(accumulator=accumulator, config=config)
        await self._run(
            chat_completion=chunks,
            mode=ChatStreamFootprintMode.DEPLOYMENT,
            strategy=strategy,
        )
        return accumulator

    async def _run(
        self,
        *,
        chat_completion: AsyncIterable[ChatCompletionChunk],
        mode: ChatStreamFootprintMode,
        strategy: _StreamStrategy,
    ) -> None:
        dispatcher = ChatStreamEventDispatcher(strategy=strategy)
        try:
            await consume_chat_completion_chunks(
                chat_completion,
                partial(parse_chat_completion_chunk, mode=mode),
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
