from dataclasses import dataclass
from typing import Optional

from aidial_sdk.chat_completion import Choice

from quickapp.common import DIAL_API_KEY
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.application import ApplicationConfig

# The _RequestContext class serves as a temporary storage for data extracted from a request.
# It is filled by _QuickAppCompletion with values such as api_key, application_config, messages, and choice.
# The AppModule DI module then uses _RequestContext to provide dependencies (api_key, choice, application_config, choice)
# to other parts of the application during the request lifecycle.


@dataclass
class _RequestContext(MessagesMixin):
    __choice: Optional[Choice] = None
    __api_key: Optional[DIAL_API_KEY] = None
    __application_config: Optional[ApplicationConfig] = None

    @property
    def api_key(self) -> DIAL_API_KEY:
        if not self.__api_key:
            raise RuntimeError("API key is not set")
        return self.__api_key

    @api_key.setter
    def api_key(self, api_key: DIAL_API_KEY) -> None:
        if self.__api_key:
            raise RuntimeError("API key is already set")
        self.__api_key = api_key

    @property
    def application_config(self) -> ApplicationConfig:
        if not self.__application_config:
            raise RuntimeError("Application config is not set")
        return self.__application_config

    @application_config.setter
    def application_config(self, application_config: ApplicationConfig) -> None:
        if self.__application_config:
            raise RuntimeError("Application config is already set")
        self.__application_config = application_config

    @property
    def choice(self) -> Choice:
        if not self.__choice:
            raise RuntimeError("Choice is not set")
        return self.__choice

    @choice.setter
    def choice(self, choice: Choice) -> None:
        if self.__choice:
            raise RuntimeError("Choice is already set")
        self.__choice = choice
