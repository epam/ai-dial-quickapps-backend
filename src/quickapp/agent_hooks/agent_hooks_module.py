import logging

from injector import Module, multiprovider

from quickapp.agent_hooks._config_driven_hooks import _ConfigDrivenToolCallHook
from quickapp.common.abstract.base_transformer import MessagesTransformer
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
        app_config: ApplicationConfig,
        tools: list[StagedBaseTool],
    ) -> list[MessagesTransformer]:
        for entry in app_config.hooks or []:
            if entry.event != HookEvent.ON_REQUEST_START:
                logger.error(
                    "Hook %r with event %r is not yet supported — skipping",
                    entry.name,
                    entry.event,
                )
        return self._build(app_config, tools, HookEvent.ON_REQUEST_START)

    @staticmethod
    def _build(
            app_config: ApplicationConfig,
        tools: list[StagedBaseTool],
        event: HookEvent,
    ) -> list[MessagesTransformer]:
        result: list[MessagesTransformer] = []
        for entry in app_config.hooks or []:
            if entry.event != event:
                continue
            match entry:
                case ToolCallHookConfig():
                    result.append(_ConfigDrivenToolCallHook(tools, entry))
        return result
