"""Prefetch orchestrator deployment metadata for each chat completion."""

from injector import inject

from quickapp.core.agent._orchestrator_static_tools_context import _OrchestratorStaticToolsContext
from quickapp.core.agent.orchestrator_capabilities import OrchestratorCapabilities
from quickapp.core.agent.orchestrator_deployment_cache_service import OrchestratorDeploymentCacheService
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.config.application import ApplicationConfig
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService


@inject
class _OrchestratorDeploymentInitializer(CompletionInitializer):
    def __init__(
        self,
        app_config: ApplicationConfig,
        tool_config_service: ToolConfigCoreService,
        orchestrator_deployment_cache: OrchestratorDeploymentCacheService,
        static_tools_context: _OrchestratorStaticToolsContext,
    ) -> None:
        self.__app_config: ApplicationConfig = app_config
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__orchestrator_deployment_cache: OrchestratorDeploymentCacheService = (
            orchestrator_deployment_cache
        )
        self._capabilities: OrchestratorCapabilities | None = None
        self._static_tools_context: _OrchestratorStaticToolsContext = static_tools_context

    async def initialize(self) -> None:
        deployment = self.__app_config.orchestrator.deployment.deployment_id
        model = await self.__orchestrator_deployment_cache.fetch_metadata(
            self.__tool_config_service.get_deployment_metadata,
            deployment,
        )
        self._capabilities = OrchestratorCapabilities(deployment=model)
        self._static_tools_context.extend_static_tools(
            ToolConfigCoreService.parse_static_tools_from_info(model)
        )

    @property
    def capabilities(self) -> OrchestratorCapabilities:
        if self._capabilities is None:
            raise RuntimeError(
                "OrchestratorCapabilities accessed before "
                "_OrchestratorDeploymentInitializer.initialize() ran"
            )
        return self._capabilities
