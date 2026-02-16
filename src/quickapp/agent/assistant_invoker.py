import logging
from typing import Any

from aidial_sdk.chat_completion import Choice
from aidial_sdk.chat_completion.request import Message
from aidial_sdk.exceptions import InvalidRequestError
from injector import inject
from openai import AsyncStream, BadRequestError, RateLimitError
from openai.lib.azure import AsyncAzureOpenAI
from openai.types.chat import ChatCompletionChunk

from quickapp.agent._attachment_filter import _AttachmentFilter
from quickapp.agent.agent_settings import AgentSettings
from quickapp.agent.message_logger import format_openai_message_pipe_tree
from quickapp.agent.models import OpenAiToolConfigDict
from quickapp.common import RESPONSE_FORMAT
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
        azure_client: AsyncAzureOpenAI,
        response_format: RESPONSE_FORMAT,
        attachment_filter: _AttachmentFilter,
        presentation_settings: PresentationSettings,
        agent_settings: AgentSettings,
    ) -> None:
        self.__attachment_filter = attachment_filter
        self.__messages: list[Message] = messages
        self.__choice: Choice = choice
        self.__config: ApplicationConfig = config
        self.__tools: list[OpenAiToolConfigDict] = tools
        self.__azure_client = azure_client
        self.__response_format = response_format
        self.__presentation_settings = presentation_settings
        self.__agent_settings = agent_settings

    async def invoke(self) -> AsyncStream[ChatCompletionChunk]:
        completion_config = self.__prepare_chat_completion_config()
        return await self.__create_chat_completion(completion_config)

    def __prepare_chat_completion_config(self) -> dict[str, Any]:

        chat_completion_config = self.__config.orchestrator.deployment.parameters.model_dump(
            exclude_none=True
        )
        prepared_messages = self.__prepare_messages(self.__messages)
        payload: dict[str, Any] = {
            "messages": prepared_messages,
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
        return chat_completion_config

    async def __create_chat_completion(
        self, completion_config: dict[str, Any]
    ) -> AsyncStream[ChatCompletionChunk]:
        try:
            chat_completion = await self.__azure_client.chat.completions.create(**completion_config)
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

    def __prepare_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        filtered_messages = self.__attachment_filter.filter_attachments(messages)
        return [message.model_dump(exclude_none=True, mode="json") for message in filtered_messages]
