import logging
from typing import Any

from aidial_sdk.chat_completion import Choice, Stage
from injector import inject
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from ._models import AssistantCallResult, Usage
from ._stage_delta_types import get_stage_index

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

        if propagate_orchestrator_stages:
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
                # bugfix issue#16 - if attachment has no data and no url, but has reference_url, use it as url
                if attachment.get("data") is None and attachment.get("url") is None:
                    if attachment.get("reference_url") is None:
                        attachment["data"] = ""
                    else:
                        attachment["url"] = attachment.get("reference_url")
                destination.add_attachment(
                    type=attachment.get("type"),
                    title=attachment.get("title"),
                    data=attachment.get("data"),
                    url=attachment.get("url"),
                    reference_url=attachment.get("reference_url"),
                    reference_type=attachment.get("reference_type"),
                )
                self.__assistant_call_result.append_attachment(attachment)

        if (
            propagate_orchestrator_stages
            and isinstance(destination, Choice)
            and (stages := custom_content.get("stages"))
            and isinstance(stages, list)
        ):
            for position, item in enumerate(stages):
                if isinstance(item, dict):
                    self.__assistant_call_result.append_stage_delta(item, position)
                    self.__stream_stage_delta(destination, item, position)

        if state := custom_content.get("state"):
            if isinstance(state, dict):
                self.__assistant_call_result.merge_state(state)

    def __stream_stage_delta(
        self, destination: Choice, item: dict[str, Any], position: int
    ) -> None:
        """Stream a single stage delta to the choice: ensure the right stage is open and append to it."""
        idx = get_stage_index(item, position)
        if self.__streaming_stage_index is not None and self.__streaming_stage_index != idx:
            self.__close_streaming_stage()
        just_created = False
        if self.__streaming_stage is None or self.__streaming_stage_index != idx:
            name = (item.get("name") or item.get("title") or "").strip() or f"Stage {idx + 1}"
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
        # Avoid duplicating name/title when we just used them for create_stage
        if not just_created:
            if item.get("name") is not None:
                stage.append_name(str(item["name"]))
            if item.get("title") is not None:
                stage.append_name(str(item["title"]))
        if item.get("content"):
            stage.append_content(str(item["content"]))
        for att in item.get("attachments") or []:
            if isinstance(att, dict):
                try:
                    stage.add_attachment(
                        type=att.get("type"),
                        title=att.get("title"),
                        data=att.get("data"),
                        url=att.get("url"),
                        reference_url=att.get("reference_url"),
                        reference_type=att.get("reference_type"),
                    )
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
