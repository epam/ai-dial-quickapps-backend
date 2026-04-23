import logging

from injector import ProviderOf, inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)


class ConfigBasedPromptProvider(PromptPartProvider):
    """Provides the basic system prompt from application configuration."""

    @inject
    def __init__(self, config_provider: ProviderOf[ApplicationConfig]):
        self.__config_provider = config_provider

    async def get_prompt_part(self) -> str:
        """Return the system prompt from config.

        Returns:
            str: The system prompt content from orchestrator configuration.
        """
        prompt = self.__config_provider.get().orchestrator.system_prompt.content or ""
        logger.debug(f"Config-based prompt part length: {len(prompt)}")
        return prompt
