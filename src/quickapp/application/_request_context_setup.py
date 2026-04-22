import logging

from aidial_sdk.chat_completion import Request
from aidial_sdk.chat_completion.choice import Choice
from aidial_sdk.deployment.configuration import ConfigurationRequest
from injector import ProviderOf, inject
from pydantic import SecretStr

from quickapp.common._di_types import CLIENT_CHANNEL_HEADER, CLIENT_CHANNEL_ID, ForwardedHeaders
from quickapp.common.forwarded_headers import extract_x_headers_from_request
from quickapp.common.tool_fallback.catch_all_scanner import log_customised_catch_all_strategies
from quickapp.config.application import ApplicationConfig
from quickapp.config.config_template_resolver import ConfigResolver

from ._request_context import _RequestContext

logger = logging.getLogger(__name__)


def _extract_client_channel_id(forwarded_headers: ForwardedHeaders) -> CLIENT_CHANNEL_ID:
    """Extract the client channel ID from forwarded headers (case-insensitive)."""
    if forwarded_headers:
        for key, value in forwarded_headers.items():
            if key.lower() == CLIENT_CHANNEL_HEADER.lower():
                return value
    return None


@inject
class _RequestContextSetup:
    def __init__(
        self,
        context_provider: ProviderOf[_RequestContext],
        config_resolver: ConfigResolver,
    ):
        self.__context_provider = context_provider
        self.__config_resolver = config_resolver

    def __resolve_application_config(self, application_properties):
        application_config = ApplicationConfig.model_validate(application_properties)
        return self.__config_resolver.resolve_config(application_config)

    async def setup(
        self, request: Request | ConfigurationRequest, choice: Choice | None = None
    ) -> None:
        context = self.__context_provider.get()
        context.api_key = SecretStr(request.api_key)
        context.bearer = SecretStr(request.bearer_token) if request.bearer_token else None

        context.application_config = self.__resolve_application_config(
            await request.request_dial_application_properties()
        )
        log_customised_catch_all_strategies(context.application_config)
        if isinstance(request, Request):
            context.forwarded_headers = extract_x_headers_from_request(request)
            context.client_channel_id = _extract_client_channel_id(context.forwarded_headers)
        if choice:
            context.choice = choice

        if isinstance(request, Request) and request.response_format:
            context.response_format = request.response_format
