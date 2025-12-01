import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common import StagedBaseTool
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.tool_initialization_exception import ToolInitializationException
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.config.toolsets.deployment import DeploymentToolSet

from ._deployment_tool_context import _DeploymentToolingContext
from ._deployment_tool_initializer import _DeploymentToolInitializer
from ._di_types import DialDeploymentToolCacheService
from .deployment_stage_wrapper import DeploymentStageWrapper
from .deployment_tool import DeploymentTool
from .dial_completion_service import DialCompletionService

logger = logging.getLogger(__name__)


class DialDeploymentToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(DialCompletionService, to=DialCompletionService, scope=request_scope)
        binder.bind(DeploymentStageWrapper, to=DeploymentStageWrapper)
        binder.bind(_DeploymentToolInitializer, to=_DeploymentToolInitializer)
        binder.bind(_DeploymentToolingContext, to=_DeploymentToolingContext, scope=request_scope)
        binder.bind(
            DialDeploymentToolCacheService, to=DialDeploymentToolCacheService, scope=singleton
        )
        logger.debug("DialDeploymentTooling module configuration completed")

    @request_scope
    @multiprovider
    def __provide_tools(
        self,
        builder: AssistedBuilder[DeploymentTool],
        app_config: ApplicationConfig,
        context: _DeploymentToolingContext,
    ) -> list[StagedBaseTool]:
        for toolset in app_config.tool_sets:
            if isinstance(toolset, DeploymentToolSet) and toolset.enabled:
                for tool in toolset.tools:
                    if isinstance(tool, DialDeploymentTool) and tool.enabled:
                        built_tool = builder.build(
                            application_id=tool.deployment.name,
                            application_name=tool.open_ai_tool.function.name,
                            description=tool.open_ai_tool.function.description,
                            content_propagation=tool.content_propagation,
                            tool_config=tool,
                        )
                        context.append_tool(built_tool)
        return context.tools

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_DeploymentToolInitializer]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def __provide_dial_simple_tool_configs(
        self, app_config: ApplicationConfig
    ) -> list[DialDeploymentSimpleTool]:
        return [
            tool
            for toolset in app_config.tool_sets
            if isinstance(toolset, DeploymentToolSet)
            for tool in getattr(toolset, "tools", [])
            if isinstance(tool, DialDeploymentSimpleTool) and tool.enabled
        ]

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _DeploymentToolingContext
    ) -> list[ToolInitializationException]:
        return context.exceptions
