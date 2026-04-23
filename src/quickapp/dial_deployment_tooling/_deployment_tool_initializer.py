import logging

from injector import AssistedBuilder, inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.deployment_tool_cache import (
    BASIC_CONFIG_CACHE_KEY_PREFIX,
    DialDeploymentToolCacheService,
)
from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.dial_app_tooling._dial_app_resolver import _DialAppResolver
from quickapp.dial_app_tooling._dial_app_resolver_context import _DialAppResolverContext
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.dial_deployment_tooling._deployment_tool_context import _DeploymentToolingContext
from quickapp.dial_deployment_tooling.deployment_tool import DeploymentTool

logger = logging.getLogger(__name__)


@inject
class _DeploymentToolInitializer(CompletionInitializer):
    def __init__(
        self,
        context: _DeploymentToolingContext,
        tool_config_service: ToolConfigCoreService,
        builder: AssistedBuilder[DeploymentTool],
        app_config: ApplicationConfig,
        deployment_cache: DialDeploymentToolCacheService,
        dial_app_resolver: _DialAppResolver,
        dial_app_resolver_context: _DialAppResolverContext,
    ):
        self.__deployment_context: _DeploymentToolingContext = context
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__builder: AssistedBuilder[DeploymentTool] = builder
        self.__app_config: ApplicationConfig = app_config
        self.__deployment_cache: DialDeploymentToolCacheService = deployment_cache
        self.__dial_app_resolver: _DialAppResolver = dial_app_resolver
        self.__dial_app_resolver_context: _DialAppResolverContext = dial_app_resolver_context

    async def initialize(self) -> None:
        await self.__dial_app_resolver.resolve()
        for toolset in self.__app_config.tool_sets:
            if isinstance(toolset, DeploymentToolSet) and toolset.enabled:
                for tool in toolset.tools:
                    if isinstance(tool, DialDeploymentTool) and tool.enabled:
                        self.__init_deployment_tool(tool)
                    if isinstance(tool, DialDeploymentSimpleTool) and tool.enabled:
                        await self.__init_simple_deployment_tool(tool)
        for _, tool_config in self.__dial_app_resolver_context.resolved_deployment_tools:
            self.__init_deployment_tool(tool_config)

    def __init_deployment_tool(self, tool: DialDeploymentTool):
        built_tool = self.__builder.build(
            application_id=tool.deployment.name,
            application_name=tool.open_ai_tool.function.name,
            description=tool.open_ai_tool.function.description,
            content_propagation=tool.content_propagation,
            tool_config=tool,
        )
        self.__deployment_context.append_tool(built_tool)

    async def __init_simple_deployment_tool(self, tool_info: DialDeploymentSimpleTool):
        try:
            tool_config = await self.__deployment_cache.get(
                f"{BASIC_CONFIG_CACHE_KEY_PREFIX}{tool_info.deployment_id}",
                self.__tool_config_service.get_basic_tool_config,
                tool_info.deployment_id,
            )
            if tool_config is None:
                raise ToolInitializationException(f"No tool config for {tool_info.deployment_id}")
            self.__init_deployment_tool(tool_config)

        except ToolInitializationException as e:
            logger.error(e, exc_info=True)
            self.__deployment_context.append_exception(e)
        except Exception as e:
            logger.error(e, exc_info=True)
            self.__deployment_context.append_exception(
                ToolInitializationException(
                    message=str(e),
                    tool_name=tool_info.deployment_id,
                    details=(
                        "\n".join(str(sub_e) for sub_e in e.exceptions)
                        if hasattr(e, "exceptions")
                        else ""
                    ),
                )
            )
