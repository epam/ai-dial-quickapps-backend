import logging

from aidial_sdk.chat_completion import Message, Role
from injector import inject
from pydantic import StrictStr

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.abstract.base_transformer import MessagesTransformer

logger = logging.getLogger(__name__)


class _AddSystemPromptTransformer(MessagesTransformer):
    @inject
    def __init__(
        self,
        prompt_providers: list[PromptPartProvider]
    ):
        self.__prompt_providers = prompt_providers
        logger.debug(f"Prompt part providers: {prompt_providers}")

    def transform(self, messages: list[Message]) -> list[Message]:
        # Construct system prompt from all providers
        prompt_parts = []
        for provider in self.__prompt_providers:
            part = provider.get_prompt_part()
            if part:  # Only add non-empty parts
                prompt_parts.append(part)

        system_prompt = "\n\n".join(prompt_parts)

        if not system_prompt:
            return messages
        if len(messages) > 0 and messages[0].role != Role.SYSTEM:
            return [Message(role=Role.SYSTEM, content=StrictStr(system_prompt))] + messages

        return messages
