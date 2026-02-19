from dataclasses import dataclass
from typing import Optional
from zoneinfo import ZoneInfo

from aidial_sdk.chat_completion import Choice, ResponseFormat
from aidial_sdk.exceptions import InvalidRequestError

from quickapp.common import DIAL_API_KEY, DIAL_BEARER
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.application import ApplicationConfig

# The _RequestContext class serves as a temporary storage for data extracted from a request.
# It is filled by _QuickAppCompletion with values such as api_key, application_config, messages, and choice.
# The AppModule DI module then uses _RequestContext to provide dependencies (api_key, choice, application_config, choice)
# to other parts of the application during the request lifecycle.


def _validate_response_format(response_format: Optional[ResponseFormat]) -> None:
    """Validate that response_format has the correct structure."""
    if response_format is None:
        return

    if response_format.type == "json_schema":
        if not hasattr(response_format, 'json_schema') or response_format.json_schema is None:
            raise InvalidRequestError(
                message="Invalid response format",
                display_message="When type is 'json_schema', the 'json_schema' field must be provided",
            )


@dataclass
class _RequestContext(MessagesMixin):
    __choice: Optional[Choice] = None
    __api_key: Optional[DIAL_API_KEY] = None
    __application_config: Optional[ApplicationConfig] = None
    __bearer_set: bool = False
    __bearer: DIAL_BEARER = None
    __response_format: Optional[ResponseFormat] = None
    __timezone: ZoneInfo = ZoneInfo("UTC")
    __timezone_set: bool = False

    @property
    def timezone(self) -> ZoneInfo:
        return self.__timezone

    @timezone.setter
    def timezone(self, tz: ZoneInfo) -> None:
        if self.__timezone_set:
            raise RuntimeError("Timezone is already set")
        self.__timezone_set = True
        self.__timezone = tz

    @property
    def bearer(self) -> DIAL_BEARER:
        if not self.__bearer_set:
            raise RuntimeError("Bearer is not set")
        return self.__bearer

    @bearer.setter
    def bearer(self, bearer: DIAL_BEARER) -> None:
        if self.__bearer_set:
            raise RuntimeError("Bearer is already set")
        self.__bearer_set = True
        self.__bearer = bearer

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

    @property
    def response_format(self) -> Optional[ResponseFormat]:
        return self.__response_format

    @response_format.setter
    def response_format(self, response_format: Optional[ResponseFormat]) -> None:
        if self.__response_format is not None:
            raise RuntimeError("Response format is already set")
        _validate_response_format(response_format)
        self.__response_format = response_format
