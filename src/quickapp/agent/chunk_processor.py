import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment, Choice, Stage, Status
from injector import inject
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from ._models import AssistantCallResult, Usage
from ._stage_delta_types import (
    StageDeltaItem,
    as_stage_delta,
    attachment_kwargs,
    get_stage_index,
    normalize_attachment,
    stage_display_name,
)

logger = logging.getLogger(__name__)


@inject
class ChunkProcessor:

    def __init__(self):
        self.__assistant_call_result = AssistantCallResult()
        self.__streaming_stages: dict[int, Stage] = {}

    async def process_chunks(
        self,
        chat_completion: AsyncStream[ChatCompletionChunk],
        destination: Choice,
        stream_content: bool = True,
        propagate_orchestrator_stages: bool = True,
    ) -> AssistantCallResult | None:
        destination.append_content("\n\r")

        async for chunk in chat_completion:
            if chunk.choices:
                for ch in chunk.choices:
                    if (content := ch.delta.content) and stream_content:
                        destination.append_content(content)
                        self.__assistant_call_result.append_content(content)

                    if custom_content := getattr(ch.delta, "custom_content", None):
                        self.__process_custom_content(
                            custom_content,
                            destination,
                            propagate_orchestrator_stages=propagate_orchestrator_stages,
                        )

                    if tool_calls_deltas_list := ch.delta.tool_calls:
                        for delta in tool_calls_deltas_list:
                            self.__assistant_call_result.append_tool_call_delta(delta)
            if chunk.usage:
                self.__assistant_call_result.set_usage(
                    Usage(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                    )
                )
        # Close any remaining open stages at the end of the stream; mark as failed since they weren't explicitly completed.
        self.__close_all_streaming_stages(status=Status.FAILED)

        self.__log_assistant_call_result(self.__assistant_call_result)
        return self.__assistant_call_result

    def __process_custom_content(
        self,
        custom_content: dict[str, Any],
        destination: Choice | Stage,
        *,
        propagate_orchestrator_stages: bool = True,
    ) -> None:
        if attachments := custom_content.get("attachments"):
            for attachment in attachments:
                if isinstance(attachment, dict):
                    normalize_attachment(attachment)
                    kwargs = attachment_kwargs(attachment)
                    destination.add_attachment(**kwargs)
                    self.__assistant_call_result.append_attachment(Attachment(**kwargs))

        if (stages := custom_content.get("stages")) and isinstance(stages, list):
            for position, raw in enumerate(stages):
                if isinstance(raw, dict):
                    delta = as_stage_delta(raw)
                    self.__assistant_call_result.append_stage_delta(delta, position)
                    if propagate_orchestrator_stages and isinstance(destination, Choice):
                        self.__stream_stage_delta(destination, delta, position)

        if state := custom_content.get("state"):
            if isinstance(state, dict):
                self.__assistant_call_result.merge_state(state)

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
    def __log_assistant_call_result(result: AssistantCallResult) -> None:
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
