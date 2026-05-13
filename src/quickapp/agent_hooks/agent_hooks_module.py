import logging

from injector import Module, ProviderOf, multiprovider

from quickapp.agent_hooks._config_driven_hooks import _ConfigDrivenToolCallHook
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.preview import preview_module
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.config.application import ApplicationConfig
from quickapp.config.hooks import HookEvent, ToolCallHookConfig

logger = logging.getLogger(__name__)


@preview_module
class AgentHooksModule(Module):

    @multiprovider
    def _provide_messages_transformers(
        self,
        app_config_provider: ProviderOf[ApplicationConfig],
        tools_provider: ProviderOf[list[StagedBaseTool]],
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ) -> list[MessagesTransformer]:
        return self._build_on_request_message_transformers(
            app_config_provider, tools_provider, HookEvent.ON_REQUEST_START, enrichers_provider
        )

    @staticmethod
    def _build_on_request_message_transformers(
        app_config_provider: ProviderOf[ApplicationConfig],
        tools_provider: ProviderOf[list[StagedBaseTool]],
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
                        _ConfigDrivenToolCallHook(tools_provider.get(), entry, enrichers_provider)
                    )
        return result
