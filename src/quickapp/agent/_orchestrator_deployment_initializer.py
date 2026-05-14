"""
Prefetch orchestrator deployment metadata for each chat completion.
"""

import logging

from injector import inject

from quickapp.agent.orchestrator_capabilities import OrchestratorCapabilities
from quickapp.agent.orchestrator_deployment_cache_service import OrchestratorDeploymentCacheService
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.config.application import ApplicationConfig
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

logger = logging.getLogger(__name__)


@inject
class _OrchestratorDeploymentInitializer(CompletionInitializer):
    def __init__(
        self,
        app_config: ApplicationConfig,
        tool_config_service: ToolConfigCoreService,
        orchestrator_deployment_cache: OrchestratorDeploymentCacheService,
    ) -> None:
        self.__app_config: ApplicationConfig = app_config
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__orchestrator_deployment_cache: OrchestratorDeploymentCacheService = (
            orchestrator_deployment_cache
        )
        self._capabilities: OrchestratorCapabilities | None = None

    async def initialize(self) -> None:
        deployment = self.__app_config.orchestrator.deployment.deployment_id
        cache_key = f"orchestrator_deployment_{deployment}"

        model = await self.__orchestrator_deployment_cache.get(
            cache_key,
            self.__tool_config_service.get_deployment_metadata,
            deployment,
        )
        if model is None:
            raise RuntimeError(
                f"Orchestrator deployment cache returned no model for '{deployment}'"
            )
        self._capabilities = OrchestratorCapabilities(deployment=model)
        logger.debug(
            "Orchestrator deployment capabilities loaded for id=%s input_attachment_types=%s",
            self._capabilities.deployment_id,
            self._capabilities.input_attachment_types,
        )

    @property
    def capabilities(self) -> OrchestratorCapabilities:
        if self._capabilities is None:
            raise RuntimeError(
                "OrchestratorCapabilities accessed before "
                "_OrchestratorDeploymentInitializer.initialize() ran"
            )
        return self._capabilities
