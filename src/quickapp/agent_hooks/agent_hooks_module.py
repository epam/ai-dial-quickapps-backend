import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider

from quickapp.agent_hooks._agent_hooks_context import _AgentHooksContext
from quickapp.agent_hooks._completion_runner import _CompletionHookRunner
from quickapp.agent_hooks._config_driven_hooks import _ConfigDrivenToolCallHook
from quickapp.agent_hooks._context_factory import HookContextFactory
from quickapp.agent_hooks._dispatcher import HookDispatcher
from quickapp.agent_hooks._handlers import HookHandlerRegistry
from quickapp.agent_hooks._hook_tool_registry import HookToolRegistry
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.abstract.completion_hook_runner import CompletionHookRunner
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.exceptions import InitializationException
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.config.hooks import HookEvent, ToolCallHookConfig

logger = logging.getLogger(__name__)


@preview_module
class AgentHooksModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_AgentHooksContext, to=_AgentHooksContext, scope=request_scope)
        binder.bind(HookContextFactory, to=HookContextFactory, scope=request_scope)
        binder.bind(HookToolRegistry, to=HookToolRegistry, scope=request_scope)
        binder.bind(HookHandlerRegistry, to=HookHandlerRegistry, scope=request_scope)
        binder.bind(HookDispatcher, to=HookDispatcher, scope=request_scope)
        binder.bind(_CompletionHookRunner, to=_CompletionHookRunner, scope=request_scope)

    @multiprovider
    def _provide_messages_transformers(
        self,
        app_config_provider: ProviderOf[ApplicationConfig],
        dispatcher: HookDispatcher,
        context_factory: HookContextFactory,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ) -> list[MessagesTransformer]:
        return self._build_on_request_message_transformers(
            app_config_provider,
            dispatcher,
            context_factory,
            HookEvent.ON_REQUEST_START,
            enrichers_provider,
        )

    @multiprovider
    def _provide_completion_hook_runners(
        self, runner: _CompletionHookRunner
    ) -> list[CompletionHookRunner]:
        return [runner]

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _AgentHooksContext
    ) -> list[InitializationException]:
        return context.exceptions

    @staticmethod
    def _build_on_request_message_transformers(
        app_config_provider: ProviderOf[ApplicationConfig],
        dispatcher: HookDispatcher,
        context_factory: HookContextFactory,
        event: HookEvent,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]] | None = None,
    ) -> list[MessagesTransformer]:
        result: list[MessagesTransformer] = []
        for entry in app_config_provider.get().hooks or []:
            if entry.event != event:
                continue
            match entry:
                case ToolCallHookConfig():
                    result.append(
                        _ConfigDrivenToolCallHook(
                            entry, dispatcher, context_factory, enrichers_provider
                        )
                    )
        return result
