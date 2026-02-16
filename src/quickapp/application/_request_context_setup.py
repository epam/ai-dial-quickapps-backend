import logging
from typing import Optional

from aidial_sdk.chat_completion import Request
from aidial_sdk.chat_completion.choice import Choice
from aidial_sdk.deployment.configuration import ConfigurationRequest
from injector import ProviderOf, inject
from pydantic import SecretStr

from quickapp.config.application import ApplicationConfig
from quickapp.config.config_template_resolver import ConfigResolver

from ._messages_setup import _MessagesSetup
from ._request_context import _RequestContext

logger = logging.getLogger(__name__)


@inject
class _RequestContextSetup:
    def __init__(
        self,
        context_provider: ProviderOf[_RequestContext],
        config_resolver: ConfigResolver,
        messages_setup: _MessagesSetup,
    ):
        self.__context_provider = context_provider
        self.__config_resolver = config_resolver
        self.__messages_setup = messages_setup

    def __resolve_application_config(self, application_properties):
        application_config = ApplicationConfig.model_validate(application_properties)
        return self.__config_resolver.resolve_config(application_config)

    async def setup(
        self, request: Request | ConfigurationRequest, choice: Optional[Choice] = None
    ) -> None:
        context = self.__context_provider.get()
        context.api_key = SecretStr(request.api_key)
        context.bearer = SecretStr(request.bearer_token) if request.bearer_token else None

        context.application_config = self.__resolve_application_config(
            await request.request_dial_application_properties()
        )
        if isinstance(request, Request):
            context.messages = self.__messages_setup.setup(request.messages)
        if choice:
            context.choice = choice

        if getattr(request, "response_format", None):
            context.response_format = request.response_format
