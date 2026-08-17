from aidial_sdk.chat_completion import Choice, ResponseFormat
from aidial_sdk.chat_completion.request import Tool
from aidial_sdk.exceptions import InvalidRequestError

from quickapp.common import (
    CLIENT_CHANNEL_ID,
    DIAL_API_KEY,
    DIAL_BEARER,
    TOOL_CHOICE,
    ACCEPT_LANGUAGE,
    ForwardedHeaders,
)
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.application import ApplicationConfig

# The _RequestContext class serves as a temporary storage for data extracted from a request.
# It is filled by _QuickAppCompletion with values such as api_key, application_config, messages, and choice.
# The AppModule DI module then uses _RequestContext to provide dependencies (api_key, choice, application_config, choice)
# to other parts of the application during the request lifecycle.


_FORBIDDEN_FORWARDED_HEADERS = frozenset({"api-key", "authorization"})


def _validate_response_format(response_format: ResponseFormat | None) -> None:
    """Validate that response_format has the correct structure."""
    if response_format is None:
        return

    if response_format.type == "json_schema":
        if not hasattr(response_format, 'json_schema') or response_format.json_schema is None:
            raise InvalidRequestError(
                message="Invalid response format",
                display_message="When type is 'json_schema', the 'json_schema' field must be provided",
            )


def _validate_forwarded_headers(value: ForwardedHeaders) -> None:
    if not value:
        return
    forbidden = sorted({key.lower() for key in value} & _FORBIDDEN_FORWARDED_HEADERS)
    if forbidden:
        raise RuntimeError(
            f"Forwarded headers must not contain auth headers: {', '.join(forbidden)}"
        )


class _RequestContext(MessagesMixin):
    _choice: Choice | None = None
    _api_key: DIAL_API_KEY | None = None
    _application_config: ApplicationConfig | None = None
    _bearer_set: bool = False
    _bearer: DIAL_BEARER = None
    _response_format: ResponseFormat | None = None
    _forwarded_headers: ForwardedHeaders | None = None
    _client_channel_id: CLIENT_CHANNEL_ID = None
    _tool_choice: TOOL_CHOICE = None
    _extra_tools: list[Tool] | None = None
    _accept_language: ACCEPT_LANGUAGE = None

    @property
    def bearer(self) -> DIAL_BEARER:
        if not self._bearer_set:
            raise RuntimeError("Bearer is not set")
        return self._bearer

    @bearer.setter
    def bearer(self, bearer: DIAL_BEARER) -> None:
        if self._bearer_set:
            raise RuntimeError("Bearer is already set")
        self._bearer_set = True
        self._bearer = bearer

    @property
    def api_key(self) -> DIAL_API_KEY:
        if not self._api_key:
            raise RuntimeError("API key is not set")
        return self._api_key

    @api_key.setter
    def api_key(self, api_key: DIAL_API_KEY) -> None:
        if self._api_key:
            raise RuntimeError("API key is already set")
        self._api_key = api_key

    @property
    def application_config(self) -> ApplicationConfig:
        if not self._application_config:
            raise RuntimeError("Application config is not set")
        return self._application_config

    @application_config.setter
    def application_config(self, application_config: ApplicationConfig) -> None:
        if self._application_config:
            raise RuntimeError("Application config is already set")
        self._application_config = application_config

    @property
    def choice(self) -> Choice:
        if not self._choice:
            raise RuntimeError("Choice is not set")
        return self._choice

    @choice.setter
    def choice(self, choice: Choice) -> None:
        if self._choice:
            raise RuntimeError("Choice is already set")
        self._choice = choice

    @property
    def response_format(self) -> ResponseFormat | None:
        return self._response_format

    @response_format.setter
    def response_format(self, response_format: ResponseFormat | None) -> None:
        if self._response_format is not None:
            raise RuntimeError("Response format is already set")
        _validate_response_format(response_format)
        self._response_format = response_format

    @property
    def forwarded_headers(self) -> ForwardedHeaders:
        return self._forwarded_headers

    @forwarded_headers.setter
    def forwarded_headers(self, value: ForwardedHeaders) -> None:
        if self._forwarded_headers is not None:
            raise RuntimeError("Forwarded headers are already set")
        _validate_forwarded_headers(value)
        self._forwarded_headers = value

    @property
    def client_channel_id(self) -> CLIENT_CHANNEL_ID:
        return self._client_channel_id

    @client_channel_id.setter
    def client_channel_id(self, value: CLIENT_CHANNEL_ID) -> None:
        if self._client_channel_id is not None:
            raise RuntimeError("Client channel ID is already set")
        self._client_channel_id = value

    @property
    def tool_choice(self) -> TOOL_CHOICE:
        return self._tool_choice

    @tool_choice.setter
    def tool_choice(self, value: TOOL_CHOICE) -> None:
        if self._tool_choice is not None:
            raise RuntimeError("Tool choice is already set")
        self._tool_choice = value

    @property
    def extra_tools(self) -> list[Tool]:
        return self._extra_tools if self._extra_tools is not None else []

    @extra_tools.setter
    def extra_tools(self, value: list[Tool]) -> None:
        if self._extra_tools is not None:
            raise RuntimeError("Extra tools are already set")
        self._extra_tools = value

    @property
    def accept_language(self) -> ACCEPT_LANGUAGE:
        return self._accept_language

    @accept_language.setter
    def accept_language(self, value: ACCEPT_LANGUAGE) -> None:
        if self._accept_language is not None:
            raise RuntimeError("Accept-Language is already set")
        self._accept_language = value
