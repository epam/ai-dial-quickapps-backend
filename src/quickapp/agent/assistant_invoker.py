import logging
from typing import Any

from aidial_sdk.chat_completion.request import Message
from injector import inject
from openai import APIError, AsyncStream, BadRequestError
from openai.types.chat import ChatCompletionChunk

from quickapp.agent._chat_completion_config_builder import _ChatCompletionConfigBuilder
from quickapp.common import ORCHESTRATOR_AZURE_CLIENT
from quickapp.common.abstract.chat_completion_recovery_policy import ChatCompletionRecoveryPolicy
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry

logger = logging.getLogger(__name__)


@inject
class AssistantInvoker:
    def __init__(
        self,
        messages: list[Message],
        azure_client: ORCHESTRATOR_AZURE_CLIENT,
        chat_completion_config_builder: _ChatCompletionConfigBuilder,
        chat_completion_recovery_policies: list[ChatCompletionRecoveryPolicy],
        deferred_stage_close_registry: DeferredStageCloseRegistry,
    ) -> None:
        self.__messages: list[Message] = messages
        self.__azure_client = azure_client
        self.__chat_completion_config_builder: _ChatCompletionConfigBuilder = (
            chat_completion_config_builder
        )
        self.__chat_completion_recovery_policies: list[ChatCompletionRecoveryPolicy] = (
            chat_completion_recovery_policies
        )
        self.__deferred_stage_close_registry: DeferredStageCloseRegistry = (
            deferred_stage_close_registry
        )

    async def invoke(self) -> AsyncStream[ChatCompletionChunk]:
        completion_config = self.__chat_completion_config_builder.build(self.__messages)
        return await self.__create_chat_completion(completion_config)

    async def __create_chat_completion(
        self, completion_config: dict[str, Any]
    ) -> AsyncStream[ChatCompletionChunk]:
        try:
            return await self.__azure_client.chat.completions.create(**completion_config)
        except (BadRequestError, APIError) as e:
            recovered = False
            for policy in self.__chat_completion_recovery_policies:
                if policy.try_recover(self.__messages, e):
                    recovered = True
            if not recovered:
                logger.exception(
                    "Chat completion rejected with BadRequest/APIError; recovery did not apply"
                )
                raise
            self.__deferred_stage_close_registry.sync_deferred_stage_ui_with_tool_messages(
                self.__messages
            )
            completion_config = self.__chat_completion_config_builder.build(self.__messages)
            try:
                return await self.__azure_client.chat.completions.create(**completion_config)
            except Exception:
                logger.exception(
                    "Error during chat completion after BadRequest/APIError recovery retry"
                )
                raise
        except Exception:
            logger.exception("Error during chat completion")
            raise
