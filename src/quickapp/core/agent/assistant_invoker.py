from aidial_sdk.chat_completion.request import Message
from injector import inject
from openai import APIError, AsyncStream
from openai.types.chat import ChatCompletionChunk

from quickapp.common import ORCHESTRATOR_AZURE_CLIENT
from quickapp.common.chat_completion_recovery import (
    CHAT_COMPLETION_CREATE_RETRY_SCOPE,
    ChatCompletionRecoveryService,
)
from quickapp.core.agent._chat_completion_config_builder import _ChatCompletionConfigBuilder


@inject
class AssistantInvoker:

    def __init__(
        self,
        messages: list[Message],
        azure_client: ORCHESTRATOR_AZURE_CLIENT,
        chat_completion_config_builder: _ChatCompletionConfigBuilder,
        chat_completion_recovery: ChatCompletionRecoveryService,
    ) -> None:
        self.__messages: list[Message] = messages
        self.__azure_client = azure_client
        self.__chat_completion_config_builder: _ChatCompletionConfigBuilder = (
            chat_completion_config_builder
        )
        self.__chat_completion_recovery = chat_completion_recovery

    async def invoke(self) -> AsyncStream[ChatCompletionChunk]:
        """Create chat completion; on APIError, run message recovery once and retry."""
        while True:
            completion_config = self.__chat_completion_config_builder.build(self.__messages)
            try:
                return await self.__azure_client.chat.completions.create(**completion_config)
            except APIError as e:
                self.__chat_completion_recovery.apply_message_recovery(
                    e, retry_scope=CHAT_COMPLETION_CREATE_RETRY_SCOPE
                )
