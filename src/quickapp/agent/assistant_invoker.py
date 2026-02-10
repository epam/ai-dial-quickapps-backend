import copy
import logging
from typing import Any

from aidial_sdk.chat_completion import Choice
from aidial_sdk.chat_completion.request import Message
from aidial_sdk.exceptions import InvalidRequestError
from injector import inject
from openai import AsyncStream, BadRequestError, RateLimitError
from openai.lib.azure import AsyncAzureOpenAI
from openai.types.chat import ChatCompletionChunk

from quickapp.agent.agent_settings import AgentSettings
from quickapp.agent.message_logger import format_openai_message_pipe_tree
from quickapp.agent.models import OpenAiToolConfigDict
from quickapp.agent.processors.pre_transformers import PreTransformer
from quickapp.common import RESPONSE_FORMAT
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)


@inject
class AssistantInvoker:
    def __init__(
        self,
        tools: list[OpenAiToolConfigDict],
        config: ApplicationConfig,
        messages_context: MessagesMixin,
        choice: Choice,
        azure_client: AsyncAzureOpenAI,
        pre_process_transformers: list[PreTransformer],
        response_format: RESPONSE_FORMAT,
        presentation_settings: PresentationSettings,
        agent_settings: AgentSettings,
    ) -> None:
        self.__messages_context: MessagesMixin = messages_context
        self.__choice: Choice = choice
        self.__config: ApplicationConfig = config
        self.__tools: list[OpenAiToolConfigDict] = tools
        self.__pre_process_transformers = pre_process_transformers or []
        self.__azure_client = azure_client
        self.__response_format = response_format
        self.__presentation_settings = presentation_settings
        self.__agent_settings = agent_settings

    async def invoke(self) -> AsyncStream[ChatCompletionChunk]:
        # Pre-process
        # TODO encapsulate pre-processing into separated class or even move somewhere before we store messages in context
        # TODO Check do we really need deep copy here or can use self.__messages_context.messages
        messages_copy = copy.deepcopy(self.__messages_context.messages)
        for transformer in self.__pre_process_transformers:
            messages_copy = transformer.transform(messages_copy)
            logger.debug(f"{type(transformer)}: {{\"result\": {messages_copy}}}")

        # Process
        self._log_messages(messages_copy)
        return await self.__create_chat_completion(messages_copy)

    async def __create_chat_completion(
        self, messages: list[Message]
    ) -> AsyncStream[ChatCompletionChunk]:
        chat_completion_config = self.__config.orchestrator.deployment.parameters.model_dump(
            exclude_none=True
        )
        serialized_messages = [
            message.model_dump(exclude_none=True, mode="json") for message in messages
        ]
        payload: dict[str, Any] = {
            "messages": serialized_messages,
            "stream": True,
            "model": self.__config.orchestrator.deployment.name,
            "tools": self.__tools,
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

        chat_completion_config.update(payload)
        logger.debug(f"Chat completion config: {chat_completion_config}")
        try:
            chat_completion = await self.__azure_client.chat.completions.create(
                **chat_completion_config
            )
        except (BadRequestError, RateLimitError) as e:
            raise InvalidRequestError(
                message=e.code,
                display_message=e.body["message"] if isinstance(e.body, dict) else e.body,
            )
        except Exception:
            logger.exception("Error during chat completion")
            raise
        return chat_completion

    def _log_messages(self, messages: list[Message]):
        preview_len = self.__agent_settings.chat_message_log_length
        for idx, msg in enumerate(messages, start=1):
            format_openai_message_pipe_tree(msg.dict(), idx, preview_len=preview_len)
