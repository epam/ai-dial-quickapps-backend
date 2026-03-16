from zoneinfo import ZoneInfo

from aidial_sdk.chat_completion import Choice, ResponseFormat
from aidial_sdk.exceptions import InvalidRequestError

from quickapp.common import DIAL_API_KEY, DIAL_BEARER, ForwardedHeaders
from quickapp.common.message_metadata import TimestampSource
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.application import ApplicationConfig

# The _RequestContext class serves as a temporary storage for data extracted from a request.
# It is filled by _QuickAppCompletion with values such as api_key, application_config, messages, and choice.
# The AppModule DI module then uses _RequestContext to provide dependencies (api_key, choice, application_config, choice)
# to other parts of the application during the request lifecycle.


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


class _RequestContext(MessagesMixin):
    _choice: Choice | None = None
    _api_key: DIAL_API_KEY | None = None
    _application_config: ApplicationConfig | None = None
    _bearer_set: bool = False
    _bearer: DIAL_BEARER = None
    _response_format: ResponseFormat | None = None
    _forwarded_headers: ForwardedHeaders | None = None
    _timezone: ZoneInfo = ZoneInfo("UTC")
    _timestamp_source: TimestampSource = TimestampSource.SERVER

    @property
    def timezone(self) -> ZoneInfo:
        return self._timezone

    @timezone.setter
    def timezone(self, tz: ZoneInfo) -> None:
        if self._timestamp_source != TimestampSource.SERVER:
            raise RuntimeError("Timezone is already set")
        self._timestamp_source = TimestampSource.USER_TIMEZONE
        self._timezone = tz

    @property
    def timestamp_source(self) -> TimestampSource:
        return self._timestamp_source

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
        self._forwarded_headers = value
