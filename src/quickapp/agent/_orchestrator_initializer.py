from typing import Any

from aidial_sdk.chat_completion.request import StaticTool
from injector import inject

from quickapp.agent._cache import OrchestratorDefaultToolsCacheService
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.config.application import ApplicationConfig
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService


class _OrchestratorDefaultToolsContext:
    def __init__(self):
        self._default_tools: list[StaticTool] = []

    @property
    def default_tools(self) -> list[StaticTool]:
        return self._default_tools

@inject
class _OrchestratorInitializer(CompletionInitializer):
    def __init__(
        self,
        app_config: ApplicationConfig,
        orchestrator_cache: OrchestratorDefaultToolsCacheService,
        tool_config_service: ToolConfigCoreService,
        orchestrator_default_tools_context: _OrchestratorDefaultToolsContext,
    ):
        self.__app_config: ApplicationConfig = app_config
        self.__orchestrator_cache: OrchestratorDefaultToolsCacheService = orchestrator_cache
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__orchestrator_default_tools_context = orchestrator_default_tools_context

    async def initialize(self) -> None:
        orchestrator = self.__app_config.orchestrator.deployment.name
        self.__orchestrator_default_tools_context.default_tools.extend(await self.__tool_config_service.get_default_tools_for_deployment(orchestrator))

