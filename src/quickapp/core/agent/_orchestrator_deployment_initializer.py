"""Prefetch orchestrator deployment metadata for each chat completion."""

import logging

from injector import inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.deployment_parameter_support import remove_unsupported_parameters
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent._orchestrator_static_tools_context import _OrchestratorStaticToolsContext
from quickapp.core.agent.orchestrator_capabilities import OrchestratorCapabilities
from quickapp.core.agent.orchestrator_deployment_cache_service import (
    OrchestratorDeploymentCacheService,
)
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

logger = logging.getLogger(__name__)


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
        self._validate_parameters()
        self._static_tools_context.extend_static_tools(
            ToolConfigCoreService.parse_static_tools_from_info(model)
        )

    def _validate_parameters(self) -> None:
        """Log each configured parameter the deployment does not support.

        `_ChatCompletionConfigBuilder` drops them on the same condition on every model call; the
        log is written here so it appears once per request rather than once per iteration.
        """
        capabilities = self.capabilities
        parameters = self.__app_config.orchestrator.deployment.parameters.model_dump(
            exclude_none=True
        )
        for name in remove_unsupported_parameters(parameters, capabilities.features):
            logger.warning(
                "Configured %s is not supported by deployment %s; dropping it",
                name,
                capabilities.deployment_id,
            )

    @property
    def capabilities(self) -> OrchestratorCapabilities:
        if self._capabilities is None:
            raise RuntimeError(
                "OrchestratorCapabilities accessed before "
                "_OrchestratorDeploymentInitializer.initialize() ran"
            )
        return self._capabilities
