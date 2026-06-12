import logging

from injector import Module, inject, multiprovider

from quickapp.core.application import Configuration
from quickapp.config.application import ApplicationConfig
from quickapp.config.starters import ConversationStartersConfig

from ._button import _Button, _create_buttons
from ._utils import create_starters_configuration

logger = logging.getLogger(__name__)


class StartersModule(Module):

    @inject
    @multiprovider
    def __provide_starters(self, app_config: ApplicationConfig) -> list[Configuration]:
        if app_config.starters:
            logger.warning(
                "The 'starters' field is deprecated and will be removed in future versions. Please use 'conversation_starters' instead."
            )
        if app_config.conversation_starters:
            return self.__provide_conversation_starters(app_config.conversation_starters)
        elif app_config.starters:
            return self.__provide_deprecated_starters(app_config.starters)
        return []

    @staticmethod
    def __provide_deprecated_starters(starters: list[str]) -> list[Configuration]:
        buttons = [
            _Button(value=i + 1, caption=starter, populateText=starter)
            for i, starter in enumerate(starters)
        ]
        return [Configuration(_create_buttons(buttons=buttons))]

    @staticmethod
    def __provide_conversation_starters(config: ConversationStartersConfig) -> list[Configuration]:
        return [Configuration(create_starters_configuration(config))]
