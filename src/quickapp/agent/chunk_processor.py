import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment, Choice, Stage
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
        # Streaming stages: at most one stage context open at a time; we stream into it as deltas arrive.
        self.__streaming_stage_cm: Any = None
        self.__streaming_stage: Stage | None = None
        self.__streaming_stage_index: int | None = None

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

        # Always close streaming stage if we ever opened one (we only open when propagate_orchestrator_stages).
        self.__close_streaming_stage()

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
        """Stream a single stage delta to the choice; delta is already StageDeltaItem from boundary."""
        idx = get_stage_index(delta, position)
        if self.__streaming_stage_index is not None and self.__streaming_stage_index != idx:
            self.__close_streaming_stage()
        just_created = False
        if self.__streaming_stage is None or self.__streaming_stage_index != idx:
            name = stage_display_name(delta, idx)
            try:
                cm = destination.create_stage(name)
                self.__streaming_stage = cm.__enter__()
                self.__streaming_stage_cm = cm
                self.__streaming_stage_index = idx
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
        if self.__streaming_stage is None:
            return
        stage = self.__streaming_stage
        if not just_created:
            if "name" in delta and delta["name"] is not None:
                stage.append_name(str(delta["name"]))
            if "title" in delta and delta["title"] is not None:
                stage.append_name(str(delta["title"]))
        if "content" in delta and delta["content"]:
            stage.append_content(str(delta["content"]))
        if "attachments" in delta and delta["attachments"]:
            for att in delta["attachments"]:
                if isinstance(att, dict):
                    try:
                        stage.add_attachment(**attachment_kwargs(att))
                    except Exception as e:
                        logger.warning("Failed to add attachment to streaming stage: %s", e)

    def __close_streaming_stage(self) -> None:
        """Close the currently open streaming stage context, if any."""
        if self.__streaming_stage_cm is None:
            return
        try:
            self.__streaming_stage_cm.__exit__(None, None, None)
            if self.__streaming_stage_index is not None:
                logger.debug(
                    "Orchestrator stage propagation: closed streaming stage (index %s)",
                    self.__streaming_stage_index,
                )
        except Exception as e:
            logger.warning("Error closing streaming stage: %s", e, exc_info=True)
        finally:
            self.__streaming_stage_cm = None
            self.__streaming_stage = None
            self.__streaming_stage_index = None

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
