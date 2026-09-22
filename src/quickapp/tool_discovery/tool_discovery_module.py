import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider

from quickapp.common import StagedBaseTool
from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent
from quickapp.tool_discovery._tool_configs import TOOL_SEARCH_TOOL_CONFIG
from quickapp.tool_discovery._tool_search_hint_prompt_provider import _ToolSearchHintPromptProvider
from quickapp.tool_discovery._tool_search_stage_wrapper import _ToolSearchStageWrapper
from quickapp.tool_discovery._tool_search_tool import _ToolSearchTool

logger = logging.getLogger(__name__)


@preview_module
class ToolDiscoveryModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_AnonymousAgent, to=_AnonymousAgent, scope=request_scope)
        binder.bind(_ToolSearchTool, to=_ToolSearchTool, scope=request_scope)
        binder.bind(_ToolSearchStageWrapper, to=_ToolSearchStageWrapper)
        binder.bind(
            _ToolSearchHintPromptProvider, to=_ToolSearchHintPromptProvider, scope=request_scope
        )

    @staticmethod
    def _is_enabled(config: ApplicationConfig) -> bool:
        return bool(
            config.orchestrator.tool_discovery and config.orchestrator.tool_discovery.enabled
        )

    @multiprovider
    def _provide_tool_search_tools(
        self,
        config: ApplicationConfig,
        tool_builder: AssistedBuilder[_ToolSearchTool],
    ) -> list[StagedBaseTool]:
        if not self._is_enabled(config):
            return []

        tool = tool_builder.build(
            tool_config=TOOL_SEARCH_TOOL_CONFIG,

        )
        logger.debug("ToolDiscoveryModule: tool_search meta-tool registered")
        return [tool]

    @multiprovider
    def _provide_prompt_parts(
        self,
        config: ApplicationConfig,
        tool_search_hint: _ToolSearchHintPromptProvider,
    ) -> list[PromptPartProvider]:
        if not self._is_enabled(config):
            return []
        return [tool_search_hint]
