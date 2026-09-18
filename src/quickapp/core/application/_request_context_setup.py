import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common._di_types import CLIENT_CHANNEL_HEADER, CLIENT_CHANNEL_ID, ForwardedHeaders
from quickapp.common.tool_fallback.catch_all_scanner import log_customised_catch_all_strategies
from quickapp.config.config_template_resolver import ConfigResolver

from ._completion_inputs import CompletionInputs
from ._messages_setup import _MessagesSetup
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
        messages_setup: _MessagesSetup,
    ):
        self.__context_provider = context_provider
        self.__config_resolver = config_resolver
        self.__messages_setup = messages_setup

    async def setup_context(self, inputs: CompletionInputs) -> None:
        """Populate every request-scoped field that does not depend on
        initializer output (api_key, application_config, forwarded headers,
        choice, response_format). ``context.messages`` is populated later by
        :meth:`setup_messages`, which runs after initializers so that feature
        contexts are available to message transformers.
        """
        context = self.__context_provider.get()
        context.api_key = inputs.api_key
        context.bearer = inputs.bearer

        context.application_config = self.__config_resolver.resolve_config(
            inputs.application_config
        )
        log_customised_catch_all_strategies(context.application_config)
        context.request_messages = inputs.messages
        context.forwarded_headers = inputs.forwarded_headers
        context.client_channel_id = _extract_client_channel_id(inputs.forwarded_headers)
        context.accept_language = inputs.accept_language
        if inputs.response_format:
            context.response_format = inputs.response_format
        if inputs.tool_choice is not None:
            context.tool_choice = inputs.tool_choice
        if inputs.extra_tools:
            context.extra_tools = inputs.extra_tools
        if inputs.choice:
            context.choice = inputs.choice

    async def setup_messages(self, messages: list[Message]) -> None:
        """Populate ``context.messages`` from the raw request messages and
        run the transformer chain over them. Called after initializers so
        transformers can see feature contexts populated during initialization.
        """
        context = self.__context_provider.get()
        external_tool_names = frozenset(t.function.name for t in context.extra_tools if t.function)
        self.__messages_setup.validate_external_tool_results(messages, external_tool_names)
        context.messages = self.__messages_setup.extract_tool_calls(messages)
        transformed = await self.__messages_setup.run_transformers(context.messages)
        context.replace_messages(transformed)
