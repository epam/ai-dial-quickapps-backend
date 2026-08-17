from aidial_client import AsyncDial
from aidial_sdk.chat_completion import ChatCompletion, Choice, Message, Stage
from fastapi import FastAPI
from fastapi_injector import request_scope
from injector import Binder, Module, multiprovider, provider, singleton

from quickapp.common import (
    CLIENT_CHANNEL_ID,
    DIAL_API_KEY,
    DIAL_BEARER,
    RESPONSE_FORMAT,
    TOOL_CHOICE,
    ACCEPT_LANGUAGE,
    ForwardedHeaders,
)
from quickapp.common.dial_settings import DialSettings
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.common.tool_timeout_utils import build_async_dial_timeout
from quickapp.config.application import ApplicationConfig
from quickapp.config.predefined_content_provider import (
    PredefinedContentProvider,
    PredefinedSettings,
)
from quickapp.shared.config_resolvers.tool_timeout_resolver import ToolTimeoutResolver

from ._initialization_error_handler import _InitializationErrorHandler
from ._messages_setup import _MessagesSetup
from ._otel_settings import _OtelSettings
from ._quick_app_application import _QuickAppApplication
from ._quick_app_completion import _QuickAppCompletion
from ._request_context import _RequestContext
from ._request_context_setup import _RequestContextSetup


class AppModule(Module):
    """
    Dependency injection module configuring the application's core and agent infrastructure.

    Sets up FastAPI integration, chat completion handler, DIAL URL, API version, and request-scoped
    dependencies using the `injector` library. Provides per-request data (API key, config, choice, stage,
    and dial client) to other components. Supports initialization and agent infrastructure by
    wiring up request context and enabling extensible agent and initializer interfaces for
    modular application structure.
    """

    def configure(self, binder: Binder) -> None:
        binder.bind(FastAPI, to=_QuickAppApplication, scope=singleton)
        binder.bind(ChatCompletion, to=_QuickAppCompletion, scope=singleton)  # type: ignore[type-abstract]
        binder.bind(DialSettings, to=DialSettings, scope=singleton)
        binder.bind(_OtelSettings, to=_OtelSettings, scope=singleton)
        binder.bind(_RequestContext, to=_RequestContext, scope=request_scope)
        binder.bind(_RequestContextSetup, to=_RequestContextSetup, scope=request_scope)
        binder.bind(_MessagesSetup, to=_MessagesSetup, scope=request_scope)
        binder.bind(PresentationSettings, to=PresentationSettings, scope=singleton)
        binder.bind(PredefinedSettings, to=PredefinedSettings, scope=singleton)
        binder.bind(PredefinedContentProvider, to=PredefinedContentProvider, scope=singleton)
        binder.bind(PerformanceTimer, to=PerformanceTimer, scope=request_scope)
        binder.bind(
            _InitializationErrorHandler, to=_InitializationErrorHandler, scope=request_scope
        )

    @provider
    def __provide_bearer(self, context: _RequestContext) -> DIAL_BEARER:
        return context.bearer

    @provider
    def __provide_api_key(self, context: _RequestContext) -> DIAL_API_KEY:
        return context.api_key

    @provider
    def __provide_application_config(self, context: _RequestContext) -> ApplicationConfig:
        return context.application_config

    @provider
    def __provide_choice(self, context: _RequestContext) -> Choice:
        return context.choice

    @provider
    def __provide_response_format(self, context: _RequestContext) -> RESPONSE_FORMAT:
        return context.response_format

    @provider
    def __provide_tool_choice(self, context: _RequestContext) -> TOOL_CHOICE:
        return context.tool_choice

    @provider
    def __provide_forwarded_headers(self, context: _RequestContext) -> ForwardedHeaders:
        return context.forwarded_headers

    @provider
    def __provide_client_channel_id(self, context: _RequestContext) -> CLIENT_CHANNEL_ID:
        return context.client_channel_id

    @provider
    def __provide_accept_language(self, context: _RequestContext) -> ACCEPT_LANGUAGE:
        return context.accept_language

    @provider
    def __provide_stage(self, choice: Choice) -> Stage:
        return choice.create_stage()

    @provider
    def __provide_async_dial(
        self,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        bearer: DIAL_BEARER,
        timeout_resolver: ToolTimeoutResolver,
    ) -> AsyncDial:
        return AsyncDial(
            base_url=dial_settings.url,
            api_key=api_key.get_secret_value(),
            api_version=dial_settings.api_version,
            bearer_token=bearer.get_secret_value() if bearer else None,
            timeout=build_async_dial_timeout(timeout_resolver.resolve()),
        )

    @provider
    def __provide_message_context(self, context: _RequestContext) -> MessagesMixin:
        return context

    @multiprovider
    def __provide_messages(self, context: _RequestContext) -> list[Message]:
        return context.messages
