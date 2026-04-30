"""
Prefetch orchestrator deployment metadata for each chat completion.
"""

from __future__ import annotations

import logging

from injector import inject

from quickapp.common import DIAL_API_KEY
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.config.application import ApplicationConfig
from quickapp.dial_core_services.orchestrator_deployment_capabilities import (
    OrchestratorCapabilities,
)
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

from .orchestrator_deployment_cache_service import OrchestratorDeploymentCacheService

logger = logging.getLogger(__name__)


@inject
class _OrchestratorDeploymentInitializer(CompletionInitializer):
    def __init__(
        self,
        app_config: ApplicationConfig,
        capabilities: OrchestratorCapabilities,
        tool_config_service: ToolConfigCoreService,
        orchestrator_deployment_cache: OrchestratorDeploymentCacheService,
        api_key: DIAL_API_KEY,
    ) -> None:
        self.__app_config: ApplicationConfig = app_config
        self.__capabilities: OrchestratorCapabilities = capabilities
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__orchestrator_deployment_cache: OrchestratorDeploymentCacheService = (
            orchestrator_deployment_cache
        )
        self.__api_key: DIAL_API_KEY = api_key

    async def initialize(self) -> None:
        deployment_id = self.__app_config.orchestrator.deployment.name
        cache_key = f"orchestrator_deployment_{deployment_id}"

        model = await self.__orchestrator_deployment_cache.get(
            cache_key,
            self.__tool_config_service.get_deployment_or_application_model,
            deployment_id,
            api_key=self.__api_key,
        )
        if model is None:
            raise RuntimeError(
                f"Orchestrator deployment cache returned no model for '{deployment_id}'"
            )
        self.__capabilities.populate_from_dial_model(model)
        logger.debug(
            "Orchestrator deployment capabilities loaded for id=%s input_attachment_types=%s",
            self.__capabilities.deployment_id,
            self.__capabilities.input_attachment_types,
        )
