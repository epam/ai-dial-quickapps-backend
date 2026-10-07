from injector import ProviderOf, inject

from quickapp.agent_hooks._handlers import resolve_hook_tool_name
from quickapp.agent_hooks._hook_tool_registry import HookToolRegistry
from quickapp.common.exceptions import HookInitializationException, InitializationException
from quickapp.config.application import ApplicationConfig
from quickapp.config.hooks import ToolCallHookConfig


@inject
class _AgentHooksContext:
    def __init__(
        self,
        app_config_provider: ProviderOf[ApplicationConfig],
        tool_registry: HookToolRegistry,
    ):
        self._app_config_provider = app_config_provider
        self._tool_registry = tool_registry
        self._exceptions: list[InitializationException] = []
        self._validated = False

    @property
    def exceptions(self) -> list[InitializationException]:
        if not self._validated:
            self._validate()
            self._validated = True
        return self._exceptions

    def _validate(self) -> None:
        tool_names = {
            tool.tool_config.open_ai_tool.function.name for tool in self._tool_registry.tools
        }
        for config in self._app_config_provider.get().hooks or []:
            if not isinstance(config, ToolCallHookConfig):
                continue
            tool_name = resolve_hook_tool_name(config)
            if tool_name not in tool_names:
                self._exceptions.append(
                    HookInitializationException(
                        message=f"tool '{tool_name}' not found in initialized tools",
                        tool_name=tool_name,
                    )
                )
