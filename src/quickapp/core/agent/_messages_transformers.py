import logging

from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import MessageContentTextPart
from injector import inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.config.agent_settings import AgentSettings
from quickapp.core.agent._prompt_providers import ConfigBasedPromptProvider

logger = logging.getLogger(__name__)


class _AddSystemPromptTransformer(MessagesTransformer):
    """Builds the system message and places it at the start of the conversation.

    An inbound system message is never passed through as is. By default it is discarded; with
    ``ALLOW_OVERRIDE_SYSTEM_MESSAGE=true`` its content replaces only the prompt configured in the
    application, while all other prompt parts (skills, MCP resources, etc.) are still appended.
    """

    @inject
    def __init__(
        self,
        prompt_providers: list[PromptPartProvider],
        agent_settings: AgentSettings,
    ):
        self.__prompt_providers = prompt_providers
        self.__settings = agent_settings
        logger.debug(f"Prompt part providers: {prompt_providers}")

    async def transform(self, messages: list[Message]) -> list[Message]:
        inbound_system: Message | None = None
        if messages and messages[0].role == Role.SYSTEM:
            inbound_system = messages[0]
            messages = messages[1:]

        override = self.__get_override(inbound_system)

        # Construct system prompt from all providers
        prompt_parts = []
        for provider in self.__prompt_providers:
            if override is not None and isinstance(provider, ConfigBasedPromptProvider):
                part = override
            else:
                part = await provider.get_prompt_part()
            if part:  # Only add non-empty parts
                prompt_parts.append(part)

        system_prompt = "\n\n".join(prompt_parts)

        if not system_prompt:
            return messages
        return [Message(role=Role.SYSTEM, content=system_prompt)] + messages

    def __get_override(self, inbound_system: Message | None) -> str | None:
        if inbound_system is None:
            return None
        if not self.__settings.allow_override_system_message:
            logger.warning("Inbound system message ignored: ALLOW_OVERRIDE_SYSTEM_MESSAGE is false")
            return None
        content = inbound_system.content
        if isinstance(content, list):
            content = "\n".join(
                part.text for part in content if isinstance(part, MessageContentTextPart)
            )
        if content:
            logger.debug("Inbound system message overrides the configured system prompt")
            return content
        logger.warning("Inbound system message ignored: it has no text content")
        return None
