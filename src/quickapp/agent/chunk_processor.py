import logging
from typing import Any

from aidial_sdk.chat_completion import Choice, Stage
from injector import inject
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from ._models import AssistantCallResult, Usage

logger = logging.getLogger(__name__)


@inject
class ChunkProcessor:

    def __init__(self):
        self.__assistant_call_result = AssistantCallResult()

    async def process_chunks(
        self,
        chat_completion: AsyncStream[ChatCompletionChunk],
        destination: Choice,
        stream_content: bool = True,
        propagate_orchestrator_stages: bool = True,
    ) -> AssistantCallResult | None:
        destination.append_content("\n\r")
        is_destination_choice = hasattr(destination, "create_stage")

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
                            is_destination_choice=is_destination_choice,
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

        if (
            is_destination_choice
            and propagate_orchestrator_stages
            and self.__assistant_call_result.stages
        ):
            self.__flush_stages_to_destination(destination)

        self.__log_assistant_call_result(self.__assistant_call_result)
        return self.__assistant_call_result

    def __process_custom_content(
        self,
        custom_content: dict[str, Any],
        destination: Choice | Stage,
        *,
        propagate_orchestrator_stages: bool = True,
        is_destination_choice: bool = False,
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
            and is_destination_choice
            and (stages := custom_content.get("stages"))
            and isinstance(stages, list)
        ):
            for position, item in enumerate(stages):
                if isinstance(item, dict):
                    self.__assistant_call_result.append_stage_delta(item, position)

        if state := custom_content.get("state"):
            if isinstance(state, dict):
                self.__assistant_call_result.merge_state(state)

    def __flush_stages_to_destination(self, destination: Choice) -> None:
        """Create one stage on the choice per accumulated stage (when propagation is enabled)."""
        stages_list = self.__assistant_call_result.stages
        try:
            created = 0
            for stage_dict in stages_list:
                name = (stage_dict.get("name") or "").strip() or "Stage"
                try:
                    with destination.create_stage(name) as stage:
                        if stage_dict.get("content"):
                            stage.append_content(stage_dict["content"])
                        for att in stage_dict.get("attachments") or []:
                            stage.add_attachment(
                                type=att.get("type"),
                                title=att.get("title"),
                                data=att.get("data"),
                                url=att.get("url"),
                                reference_url=att.get("reference_url"),
                                reference_type=att.get("reference_type"),
                            )
                    created += 1
                except Exception as e:
                    logger.warning(
                        "Orchestrator stage creation failed for %r, skipping stage: %s",
                        name,
                        e,
                        exc_info=True,
                    )
            logger.debug(
                "Orchestrator stage propagation: created %d stage(s) on choice",
                created,
            )
        except Exception as e:
            logger.warning(
                "Orchestrator stage propagation failed, skipping all stages: %s",
                e,
                exc_info=True,
            )

    @staticmethod
    def __log_assistant_call_result(result: AssistantCallResult) -> None:
        logger.debug("===================")
        logger.debug(" ---- Captured values:")
        logger.debug(f" ----- text llm response: %s", result.content)
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
