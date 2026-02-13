import logging

from aidial_sdk.chat_completion import Message, Role
from injector import ProviderOf, inject
from pydantic import StrictStr

from quickapp.agent.agent_instructions_provider import AgentInstructionsProvider
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)


class _AddSystemPromptTransformer(MessagesTransformer):
    @inject
    def __init__(
        self,
        config_provider: ProviderOf[ApplicationConfig],
        instructions_provider: AgentInstructionsProvider,
    ):
        self.__config_provider = config_provider
        self.__instructions_provider = instructions_provider

    def transform(self, messages: list[Message]) -> list[Message]:
        parts = (
            self.__config_provider.get().orchestrator.system_prompt.content or "",
            self.__instructions_provider.get() or "",
        )
        combined_system_prompt = "\n\n".join(p for p in parts if p)

        if not isinstance(messages, list):
            raise TypeError("Data must be a list of Message objects")
        if not combined_system_prompt:
            return messages
        if len(messages) > 0 and messages[0].role != Role.SYSTEM:
            return [Message(role=Role.SYSTEM, content=StrictStr(combined_system_prompt))] + messages

        return messages
