import logging
from functools import partial
from typing import Any

from aidial_sdk.chat_completion import Choice, Stage, Status
from injector import inject
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from quickapp.common.chat_completion_stream import (
    ChatStreamAccumulator,
    ChatStreamEvent,
    ChatStreamFootprintMode,
    ChunkUsageFootprint,
    NormalizedCustomContent,
    consume_chat_completion_chunks,
    parse_chat_completion_chunk,
)

from ..common.base_stage_wrapper import BaseStageWrapper
from ._stage_delta_types import (
    StageDeltaItem,
    as_stage_delta,
    attachment_kwargs,
    get_stage_index,
    stage_display_name,
)

logger = logging.getLogger(__name__)


@inject
class ChunkProcessor:

    def __init__(self):
        self.__accumulator = ChatStreamAccumulator()
        self.__streaming_stages: dict[int, Stage] = {}

    async def process_chunks(
        self,
        chat_completion: AsyncStream[ChatCompletionChunk],
        destination: Choice,
        stream_content: bool = True,
        propagate_orchestrator_stages: bool = True,
    ) -> ChatStreamAccumulator | None:
        destination.append_content("\n\r")

        result = self.__accumulator
        outer = self
        dest = destination
        sc = stream_content
        po = propagate_orchestrator_stages

        def on_stream_event(event: ChatStreamEvent) -> None:
            if isinstance(event, ChunkUsageFootprint):
                result.apply_usage_footprint(event, mode=ChatStreamFootprintMode.ORCHESTRATOR)
                return
            delta = event
            if (content := delta.content) and sc:
                if dest:
                    dest.append_content(content)
                result.append_content(content)
            if delta.custom is not None:
                outer._apply_normalized_custom_content(
                    delta.custom,
                    dest,
                    propagate_orchestrator_stages=po,
                )
            for tc in delta.tool_calls:
                result.append_tool_call_delta(tc)

        await consume_chat_completion_chunks(
            chat_completion,
            partial(
                parse_chat_completion_chunk,
                mode=ChatStreamFootprintMode.ORCHESTRATOR,
            ),
            on_stream_event,
        )

        self.__close_all_streaming_stages(status=Status.FAILED)

        self.__log_stream_accumulator(self.__accumulator)
        return self.__accumulator

    def _apply_normalized_custom_content(
        self,
        norm: NormalizedCustomContent,
        destination: Choice | Stage | BaseStageWrapper | None = None,
        *,
        propagate_orchestrator_stages: bool = True,
    ) -> None:
        for attachment in norm.sdk_attachments:
            if destination:
                self._fix_attachment(attachment)
                destination.add_attachment(**attachment.model_dump())
            self.__accumulator.append_attachment(attachment)

        for position, raw in norm.stage_entries:
            delta = as_stage_delta(raw)
            self.__accumulator.append_stage_delta(delta, position)
            if propagate_orchestrator_stages and isinstance(destination, Choice):
                self.__stream_stage_delta(destination, delta, position)

        if norm.state is not None:
            self.__accumulator.merge_state(norm.state)

    @staticmethod
    def _fix_attachment(attachment: Any) -> None:
        """Bugfix issue#16: if attachment has no data and no url, use reference_url as url."""
        if attachment.data is None and attachment.url is None:
            if attachment.reference_url is None:
                attachment["data"] = ""
            else:
                attachment.url = attachment.reference_url

    def __stream_stage_delta(
        self, destination: Choice, delta: StageDeltaItem, position: int
    ) -> None:
        """Stream a single stage delta to the choice; supports interleaved deltas by index."""
        idx = get_stage_index(delta, position)
        just_created = False
        if idx not in self.__streaming_stages:
            name = stage_display_name(delta)
            try:
                stage = destination.create_stage(name)
                stage.open()
                self.__streaming_stages[idx] = stage
                just_created = True
            except Exception as e:
                logger.warning(
                    "Orchestrator streaming stage creation failed for index %s (%r): %s",
                    idx,
                    name,
                    e,
                    exc_info=True,
                )
                return
        stage = self.__streaming_stages[idx]
        if not just_created and "name" in delta and delta["name"] is not None:
            stage.append_name(str(delta["name"]))
        if "content" in delta and delta["content"]:
            stage.append_content(str(delta["content"]))
        if "attachments" in delta and delta["attachments"]:
            for att in delta["attachments"]:
                if isinstance(att, dict):
                    try:
                        stage.add_attachment(**attachment_kwargs(att))
                    except Exception as e:
                        logger.warning("Failed to add attachment to streaming stage: %s", e)
        if "status" in delta and delta["status"] is not None:
            status = (
                Status.COMPLETED
                if str(delta["status"]).lower() == Status.COMPLETED.value
                else Status.FAILED
            )
            self.__close_streaming_stage_at_index(idx, status)

    def __close_streaming_stage_at_index(self, idx: int, stage_status: Status) -> None:
        """Close the streaming stage for the given index and remove it from the dict."""
        stage = self.__streaming_stages.pop(idx, None)
        if stage is None:
            return
        try:
            stage.close(status=stage_status)
            logger.debug(
                "Orchestrator stage propagation: closed streaming stage (index %s)",
                idx,
            )
        except Exception as e:
            logger.warning("Error closing streaming stage: %s", e, exc_info=True)

    def __close_all_streaming_stages(self, status: Status) -> None:
        """Close all open streaming stages (e.g. at stream end)."""
        for idx in sorted(self.__streaming_stages.keys()):
            self.__close_streaming_stage_at_index(idx, status)

    @staticmethod
    def __log_stream_accumulator(result: ChatStreamAccumulator) -> None:
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
