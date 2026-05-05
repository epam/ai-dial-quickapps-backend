import json
import logging
from typing import Any

from aidial_sdk.chat_completion import Choice
from aidial_sdk.chat_completion.request import Message
from injector import inject
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from quickapp.agent._orchestrator_default_tools import OrchestratorDefaultToolsService
from quickapp.agent.agent_settings import AgentSettings
from quickapp.agent.message_logger import format_openai_message_pipe_tree
from quickapp.agent.models import STATE_KEY_ORCHESTRATOR, OpenAiToolConfigDict
from quickapp.common import ORCHESTRATOR_AZURE_CLIENT, RESPONSE_FORMAT, ForwardedHeaders
from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)


@inject
class AssistantInvoker:
    def __init__(
        self,
        tools: list[OpenAiToolConfigDict],
        config: ApplicationConfig,
        messages: list[Message],
        choice: Choice,
        azure_client: ORCHESTRATOR_AZURE_CLIENT,
        response_format: RESPONSE_FORMAT,
        pre_invocation_transformers: list[PreInvocationTransformer],
        presentation_settings: PresentationSettings,
        agent_settings: AgentSettings,
        forwarded_headers: ForwardedHeaders,
        default_tools_service: OrchestratorDefaultToolsService,
    ) -> None:
        self.__pre_invocation_transformers = pre_invocation_transformers
        self.__messages: list[Message] = messages
        self.__choice: Choice = choice
        self.__config: ApplicationConfig = config
        self.__tools: list[OpenAiToolConfigDict] = tools
        self.__azure_client = azure_client
        self.__response_format = response_format
        self.__presentation_settings = presentation_settings
        self.__agent_settings = agent_settings
        self.__forwarded_headers = forwarded_headers
        self.__default_tools_service = default_tools_service

    async def invoke(self) -> AsyncStream[ChatCompletionChunk]:
        deployment = self.__config.orchestrator.deployment.name
        default_tools = await self.__default_tools_service.get_default_tools(deployment)
        merged_tools: list[dict[str, Any]] = list(default_tools) + list(self.__tools)
        if default_tools:
            logger.info(
                "Merged %d default tool(s) for deployment %s with %d app tool(s)",
                len(default_tools),
                deployment,
                len(self.__tools),
            )
        completion_config = self.__prepare_chat_completion_config(tools=merged_tools)
        return await self.__create_chat_completion(completion_config)

    def __prepare_chat_completion_config(
        self,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tools_to_use = tools if tools is not None else self.__tools
        chat_completion_config = self.__config.orchestrator.deployment.parameters.model_dump(
            exclude_none=True
        )
        prepared_messages = self.__prepare_messages(self.__messages)
        payload: dict[str, Any] = {
            "messages": prepared_messages,
            "stream": True,
            "model": self.__config.orchestrator.deployment.name,
            "tools": tools_to_use,
        }

        if self.__response_format:
            logger.debug("Setting response format: %s", self.__response_format)
            if hasattr(self.__response_format, "model_dump"):
                payload["response_format"] = self.__response_format.model_dump(
                    exclude_none=True, mode="json"
                )
            elif isinstance(self.__response_format, dict):
                payload["response_format"] = self.__response_format
            else:
                logger.error(
                    "Unsupported response format type: %s. The response format will not be applied.",
                    type(self.__response_format),
                )

        if self.__presentation_settings.show_usage_statistics:
            payload["stream_options"] = {"include_usage": True}

        if self.__forwarded_headers:
            payload["extra_headers"] = self.__forwarded_headers

        chat_completion_config.update(payload)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Chat completion config: %s", json.dumps(chat_completion_config, ensure_ascii=False)
            )
        return chat_completion_config

    async def __create_chat_completion(
        self, completion_config: dict[str, Any]
    ) -> AsyncStream[ChatCompletionChunk]:
        try:
            chat_completion = await self.__azure_client.chat.completions.create(**completion_config)
        except Exception:
            logger.exception("Error during chat completion")
            raise
        return chat_completion

    def _log_messages(self, messages: list[Message]):
        preview_len = self.__agent_settings.chat_message_log_length
        for idx, msg in enumerate(messages, start=1):
            format_openai_message_pipe_tree(msg.dict(), idx, preview_len=preview_len)

    def __prepare_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        transformed_messages = messages
        for transformer in self.__pre_invocation_transformers:
            transformed_messages = transformer.transform(transformed_messages)
        result: list[dict[str, Any]] = []
        for message in transformed_messages:
            msg_dict = message.model_dump(exclude_none=True, mode="json")
            self.__promote_orchestrator_state_to_top_level(msg_dict)
            result.append(msg_dict)
        return result

    @staticmethod
    def __promote_orchestrator_state_to_top_level(msg_dict: dict[str, Any]) -> None:
        """Before calling the model, promote state.orchestrator to top-level state."""
        custom = msg_dict.get("custom_content")
        if not isinstance(custom, dict):
            return
        state = custom.get("state")
        if not isinstance(state, dict) or STATE_KEY_ORCHESTRATOR not in state:
            return
        orch = state.pop(STATE_KEY_ORCHESTRATOR, None)
        if isinstance(orch, dict):
            state.update(orch)
