import logging

from injector import AssistedBuilder, inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.tool_initialization_exception import ToolInitializationException
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.dial_deployment_tooling._deployment_tool_context import _DeploymentToolingContext
from quickapp.dial_deployment_tooling._di_types import DialDeploymentToolCacheService
from quickapp.dial_deployment_tooling.deployment_tool import DeploymentTool

logger = logging.getLogger(__name__)


@inject
class _DeploymentToolInitializer(CompletionInitializer):
    def __init__(
        self,
        tool_list: list[DialDeploymentSimpleTool],
        context: _DeploymentToolingContext,
        tool_config_service: ToolConfigCoreService,
        builder: AssistedBuilder[DeploymentTool],
        deployment_cache: DialDeploymentToolCacheService,
    ):
        self.__tool_list: list[DialDeploymentSimpleTool] = tool_list
        self.__deployment_context: _DeploymentToolingContext = context
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__builder: AssistedBuilder[DeploymentTool] = builder
        self.__deployment_cache: DialDeploymentToolCacheService = deployment_cache

    async def initialize(self) -> None:
        if not self.__tool_list:
            return

        for tool_info in self.__tool_list:
            try:
                tool_config = await self.__deployment_cache.get(
                    f"basic_config_{tool_info.deployment_id}",
                    self.__tool_config_service.get_basic_tool_config,
                    tool_info.deployment_id,
                )
                if tool_config is None:
                    continue

                tool = self.__builder.build(
                    application_id=tool_config.deployment.name,
                    application_name=tool_config.open_ai_tool.function.name,
                    description=tool_config.open_ai_tool.function.description,
                    content_propagation=tool_config.content_propagation,
                    tool_config=tool_config,
                )
                self.__deployment_context.append_tool(tool)  # type: ignore[arg-type]
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
