import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common import StagedBaseTool
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.tool_initialization_exception import ToolInitializationException
from quickapp.config.application import ApplicationConfig
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPToolSet
from quickapp.mcp_tooling._di_types import DialToolsetCacheService
from quickapp.mcp_tooling._mcp_connection_manager import _MCPConnectionManager
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper
from quickapp.mcp_tooling._mcp_tool import _MCPTool
from quickapp.mcp_tooling._mcp_tool_initializer import _MCPToolInitializer
from quickapp.mcp_tooling._mcp_tooling_context import _MCPToolingContext

logger = logging.getLogger(__name__)


class MCPToolingModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(_MCPToolInitializer, to=_MCPToolInitializer)
        binder.bind(_MCPToolingContext, to=_MCPToolingContext, scope=request_scope)
        binder.bind(_MCPStageWrapper, to=_MCPStageWrapper)
        binder.bind(_MCPTool, to=_MCPTool)
        binder.bind(_MCPConnectionManager, to=_MCPConnectionManager)
        binder.bind(DialToolsetCacheService, to=DialToolsetCacheService, scope=singleton)
        logger.debug("MCPToolingModule module configuration completed")

    @request_scope
    @multiprovider
    def __provide_mcp_toolsets(
        self, app_config: ApplicationConfig
    ) -> list[MCPToolSet | DialMCPToolSet]:
        return [
            toolset_info
            for toolset_info in (app_config.tool_sets or [])
            if isinstance(toolset_info, MCPToolSet) or isinstance(toolset_info, DialMCPToolSet)
        ]

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_MCPToolInitializer]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @request_scope
    @multiprovider
    def _provide_mcp_tools(self, mcp_context: _MCPToolingContext) -> list[StagedBaseTool]:
        return mcp_context.tools

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _MCPToolingContext
    ) -> list[ToolInitializationException]:
        return context.exceptions
