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
        simple_tools_provider: ProviderOf[list[DialDeploymentSimpleTool]],
        app_config: ApplicationConfig,
    ):
        self.__deployment_context: _DeploymentToolingContext = context
        self.__deferred_context: _DeploymentDeferredToolsContext = deferred_context
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__builder: AssistedBuilder[DeploymentTool] = builder
        self.__deployment_cache: DialDeploymentToolCacheService = deployment_cache
        # Resolved lazily in initialize() because dial_app_tooling contributes
        # to the DialDeploymentTool multibinder only after _DialAppResolver runs.
        self.__dial_tools_provider: ProviderOf[list[DialDeploymentTool]] = dial_tools_provider
        self.__simple_tools_provider: ProviderOf[list[DialDeploymentSimpleTool]] = (
            simple_tools_provider
        )
        self.__app_config: ApplicationConfig = app_config

    async def initialize(self) -> None:
        # Tools configured directly under a DeploymentToolSet are grouped by their owning
        # toolset (identified by object identity) so the toolset's tool count can be checked
        # against the deferral threshold. Tools synthesized by dial_app_tooling (from a
        # DialAppToolSet) have no such owner and are always eager — a DialAppToolSet always
        # resolves to exactly one deployment tool, so batching never applies to them anyway.
        owner_by_tool_id = self.__build_owner_map()
        groups: dict[int, list[StagedBaseTool]] = {}
        toolset_by_group_key: dict[int, DeploymentToolSet] = {}
        ungrouped: list[StagedBaseTool] = []

        for tool in self.__dial_tools_provider.get():
            built_tool = self.__build_deployment_tool(tool)
            self.__bucket_tool(
                built_tool, owner_by_tool_id.get(id(tool)), groups, toolset_by_group_key, ungrouped
            )

        for simple_tool in self.__simple_tools_provider.get():
            built_simple_tool = await self.__build_simple_deployment_tool(simple_tool)
            if built_simple_tool is None:
                continue
            self.__bucket_tool(
                built_simple_tool,
                owner_by_tool_id.get(id(simple_tool)),
                groups,
                toolset_by_group_key,
                ungrouped,
            )

        discovery_cfg = self.__app_config.orchestrator.tool_discovery
        for group_key, tools in groups.items():
            toolset = toolset_by_group_key[group_key]
            if is_toolset_deferred(toolset, discovery_cfg, len(tools)):
                self.__deferred_context.register_deferred_tools(toolset, tools)
                logger.debug(
                    "Deferred %d tools from deployment toolset '%s' into the deferred tools registry",
                    len(tools),
                    resolve_localized(toolset.name),
                )
            self.__deployment_context.extend_tools(tools)

        self.__deployment_context.extend_tools(ungrouped)

    def __build_owner_map(self) -> dict[int, DeploymentToolSet]:
        owner_by_tool_id: dict[int, DeploymentToolSet] = {}
        for toolset in self.__app_config.tool_sets or []:
            if not isinstance(toolset, DeploymentToolSet) or not toolset.enabled:
                continue
            for tool_config in toolset.tools:
                if isinstance(tool_config, (DialDeploymentTool, DialDeploymentSimpleTool)):
                    owner_by_tool_id[id(tool_config)] = toolset
        return owner_by_tool_id

    @staticmethod
    def __bucket_tool(
        built_tool: StagedBaseTool,
        owner: DeploymentToolSet | None,
        groups: dict[int, list[StagedBaseTool]],
        toolset_by_group_key: dict[int, DeploymentToolSet],
        ungrouped: list[StagedBaseTool],
    ) -> None:
        if owner is None:
            ungrouped.append(built_tool)
            return
        group_key = id(owner)
        groups.setdefault(group_key, []).append(built_tool)
        toolset_by_group_key[group_key] = owner

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
