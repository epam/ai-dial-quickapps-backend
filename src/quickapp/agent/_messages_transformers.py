import logging

from aidial_sdk.chat_completion import Message, Role
from injector import ProviderOf, inject
from pydantic import StrictStr

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)


class _AddSystemPromptTransformer(MessagesTransformer):
    @inject
    def __init__(
        self,
        config_provider: ProviderOf[ApplicationConfig]
    ):
        self.__config_provider = config_provider

    def transform(self, messages: list[Message]) -> list[Message]:
        system_prompt = self.__config_provider.get().orchestrator.system_prompt.content or ""
        if not system_prompt:
            return messages
        if len(messages) > 0 and messages[0].role != Role.SYSTEM:
            return [Message(role=Role.SYSTEM, content=StrictStr(system_prompt))] + messages

        return messages
