import logging

from injector import AssistedBuilder, ProviderOf, inject

from quickapp.common import StagedBaseTool
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.deferred_tools_accumulator import is_toolset_deferred
from quickapp.common.deployment_tool_cache import DialDeploymentToolCacheService
from quickapp.common.exceptions import ToolInitializationException
from quickapp.common.localized_string import resolve_localized
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.dial_deployment_tooling._deployment_deferred_tools_context import (
    _DeploymentDeferredToolsContext,
)
from quickapp.dial_deployment_tooling._deployment_tool_context import _DeploymentToolingContext
from quickapp.dial_deployment_tooling.deployment_tool import DeploymentTool
from quickapp.shared.user_access import ToolAccessFilter

logger = logging.getLogger(__name__)


@inject
class _DeploymentToolInitializer(CompletionInitializer):
    def __init__(
        self,
        context: _DeploymentToolingContext,
        deferred_context: _DeploymentDeferredToolsContext,
        tool_config_service: ToolConfigCoreService,
        builder: AssistedBuilder[DeploymentTool],
        deployment_cache: DialDeploymentToolCacheService,
        dial_tools_provider: ProviderOf[list[DialDeploymentTool]],
        app_config: ApplicationConfig,
        access_filter: ToolAccessFilter,
    ):
        self.__deployment_context: _DeploymentToolingContext = context
        self.__deferred_context: _DeploymentDeferredToolsContext = deferred_context
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__builder: AssistedBuilder[DeploymentTool] = builder
        self.__deployment_cache: DialDeploymentToolCacheService = deployment_cache
        # Resolved lazily in initialize() because dial_app_tooling contributes to the
        # DialDeploymentTool multibinder only after _DialAppResolver runs. By the time
        # initialize() runs, this carries only tools synthesized from a DialAppToolSet —
        # they have no owning DeploymentToolSet in app_config.tool_sets and are always eager.
        self.__dial_tools_provider: ProviderOf[list[DialDeploymentTool]] = dial_tools_provider
        self.__app_config: ApplicationConfig = app_config
        self.__access_filter: ToolAccessFilter = access_filter

    async def initialize(self) -> None:
        discovery_cfg = self.__app_config.orchestrator.tool_discovery

        for toolset in self.__app_config.tool_sets or []:
            if not isinstance(toolset, DeploymentToolSet) or not toolset.enabled:
                continue
            tools = await self.__build_toolset_tools(toolset)
            if is_toolset_deferred(toolset, discovery_cfg, len(tools)):
                self.__deferred_context.register_deferred_tools(toolset, tools)
                logger.debug(
                    "Deferred %d tools from deployment toolset '%s' into the deferred tools registry",
                    len(tools),
                    resolve_localized(toolset.name),
                )
            self.__deployment_context.extend_tools(tools)

        # A DialAppToolSet always resolves to exactly one deployment tool, so batching
        # never applies to these — they're extended unconditionally, without deferral.
        synthesized_tools = [
            self.__build_deployment_tool(tool) for tool in self.__dial_tools_provider.get()
        ]
        self.__deployment_context.extend_tools(synthesized_tools)

    async def __build_toolset_tools(self, toolset: DeploymentToolSet) -> list[StagedBaseTool]:
        tools: list[StagedBaseTool] = []
        for tool_config in toolset.tools:
            if isinstance(tool_config, DialDeploymentTool) and tool_config.enabled:
                if await self.__access_filter.is_accessible(tool_config.deployment.deployment_id):
                    tools.append(self.__build_deployment_tool(tool_config))
                else:
                    logger.debug("Skipping a deployment tool the user cannot access")
            elif isinstance(tool_config, DialDeploymentSimpleTool) and tool_config.enabled:
                # Checked before the metadata fetch, so inaccessible simple tools cost no round-trips.
                if not await self.__access_filter.is_accessible(tool_config.deployment_id):
                    logger.debug("Skipping a deployment tool the user cannot access")
                    continue
                built_simple_tool = await self.__build_simple_deployment_tool(tool_config)
                if built_simple_tool is not None:
                    tools.append(built_simple_tool)
        return tools

    def __build_deployment_tool(self, tool: DialDeploymentTool) -> StagedBaseTool:
        return self.__builder.build(
            application_id=tool.deployment.deployment_id,
            application_name=tool.open_ai_tool.function.name,
            description=tool.open_ai_tool.function.description,
            content_propagation=tool.content_propagation,
            tool_config=tool,
        )

    async def __build_simple_deployment_tool(
        self, tool_info: DialDeploymentSimpleTool
    ) -> StagedBaseTool | None:
        try:
            tool_config = await self.__deployment_cache.fetch_basic_tool_config(
                self.__tool_config_service.get_basic_tool_config,
                tool_info.deployment_id,
            )
            overrides = {
                name: value
                for name, value in (
                    ("conversation_mode", tool_info.conversation_mode),
                    (
                        "propagate_annotations_to_choice",
                        tool_info.propagate_annotations_to_choice,
                    ),
                )
                if value is not None
            }
            if overrides:
                tool_config = tool_config.model_copy(update=overrides)
            return self.__build_deployment_tool(tool_config)

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
        return None
