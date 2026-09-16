"""Prefetch orchestrator deployment metadata for each chat completion."""

import logging

from injector import inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException, UnsupportedReasoningEffortException
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
        self._initialization_exceptions: list[InitializationException] = []

    async def initialize(self) -> None:
        deployment = self.__app_config.orchestrator.deployment.deployment_id
        model = await self.__orchestrator_deployment_cache.fetch_metadata(
            self.__tool_config_service.get_deployment_metadata,
            deployment,
        )
        self._capabilities = OrchestratorCapabilities(deployment=model)
        self._validate_reasoning_effort()
        self._static_tools_context.extend_static_tools(
            ToolConfigCoreService.parse_static_tools_from_info(model)
        )

    def _validate_reasoning_effort(self) -> None:
        """Record an issue when the configured reasoning effort is not advertised.

        `_ChatCompletionConfigBuilder` drops the parameter on the same condition; the issue
        exists so the drop is visible to the app builder rather than silent.
        """
        capabilities = self.capabilities
        reasoning_effort = self.__app_config.orchestrator.deployment.parameters.reasoning_effort
        if reasoning_effort is None or capabilities.supports_reasoning_effort(reasoning_effort):
            return
        logger.warning(
            "Configured reasoning_effort is not advertised by deployment %s; dropping it "
            "(advertised values: %d)",
            capabilities.deployment_id,
            len(capabilities.reasoning_efforts),
        )
        self._initialization_exceptions.append(
            UnsupportedReasoningEffortException(
                requested=reasoning_effort,
                supported=capabilities.reasoning_efforts,
            )
        )

    @property
    def initialization_exceptions(self) -> list[InitializationException]:
        return self._initialization_exceptions

    @property
    def capabilities(self) -> OrchestratorCapabilities:
        if self._capabilities is None:
            raise RuntimeError(
                "OrchestratorCapabilities accessed before "
                "_OrchestratorDeploymentInitializer.initialize() ran"
            )
        return self._capabilities
