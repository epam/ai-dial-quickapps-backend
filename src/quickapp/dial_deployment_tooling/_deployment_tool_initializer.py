import logging

from injector import AssistedBuilder, ProviderOf, inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.deployment_tool_cache import DialDeploymentToolCacheService
from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
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
        deployment_cache: DialDeploymentToolCacheService,
        dial_tools_provider: ProviderOf[list[DialDeploymentTool]],
        simple_tools_provider: ProviderOf[list[DialDeploymentSimpleTool]],
    ):
        self.__deployment_context: _DeploymentToolingContext = context
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__builder: AssistedBuilder[DeploymentTool] = builder
        self.__deployment_cache: DialDeploymentToolCacheService = deployment_cache
        # Resolved lazily in initialize() because dial_app_tooling contributes
        # to the DialDeploymentTool multibinder only after _DialAppResolver runs.
        self.__dial_tools_provider: ProviderOf[list[DialDeploymentTool]] = dial_tools_provider
        self.__simple_tools_provider: ProviderOf[list[DialDeploymentSimpleTool]] = (
            simple_tools_provider
        )

    async def initialize(self) -> None:
        for tool in self.__dial_tools_provider.get():
            self.__init_deployment_tool(tool)
        for simple_tool in self.__simple_tools_provider.get():
            await self.__init_simple_deployment_tool(simple_tool)

    def __init_deployment_tool(self, tool: DialDeploymentTool):
        built_tool = self.__builder.build(
            application_id=tool.deployment.deployment_id,
            application_name=tool.open_ai_tool.function.name,
            description=tool.open_ai_tool.function.description,
            content_propagation=tool.content_propagation,
            tool_config=tool,
        )
        self.__deployment_context.append_tool(built_tool)

    async def __init_simple_deployment_tool(self, tool_info: DialDeploymentSimpleTool):
        try:
            tool_config = await self.__deployment_cache.fetch_basic_tool_config(
                self.__tool_config_service.get_basic_tool_config,
                tool_info.deployment_id,
            )
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
