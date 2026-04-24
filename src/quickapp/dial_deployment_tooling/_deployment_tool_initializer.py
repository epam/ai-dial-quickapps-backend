import logging

from injector import AssistedBuilder, inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.dial_deployment_tooling._deployment_tool_context import _DeploymentToolingContext
from quickapp.dial_deployment_tooling._di_types import DialDeploymentToolCacheService
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
    ):
        self.__deployment_context: _DeploymentToolingContext = context
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__builder: AssistedBuilder[DeploymentTool] = builder
        self.__app_config: ApplicationConfig = app_config
        self.__deployment_cache: DialDeploymentToolCacheService = deployment_cache

    async def initialize(self) -> None:
        for toolset in self.__app_config.tool_sets:
            if isinstance(toolset, DeploymentToolSet) and toolset.enabled:
                for tool in toolset.tools:
                    if isinstance(tool, DialDeploymentTool) and tool.enabled:
                        self.__init_deployment_tool(tool)
                    if isinstance(tool, DialDeploymentSimpleTool) and tool.enabled:
                        await self.__init_simple_deployment_tool(tool)

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
                f"basic_config_{tool_info.deployment_id}",
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
