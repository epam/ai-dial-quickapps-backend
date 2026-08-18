import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common import StagedBaseTool
from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException
from quickapp.common.tool_names import INTERNAL_MCP_READ_RESOURCE_TOOL_NAME
from quickapp.config.application import ApplicationConfig
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPToolSet
from quickapp.mcp_tooling._di_types import DialToolsetCacheService
from quickapp.mcp_tooling._mcp_eager_resource_transformer import _MCPEagerResourceTransformer
from quickapp.mcp_tooling._mcp_resource_card_provider import _MCPResourceCardProvider
from quickapp.mcp_tooling._mcp_session_manager import _MCPSessionManager
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper
from quickapp.mcp_tooling._mcp_tool import _MCPTool
from quickapp.mcp_tooling._mcp_tool_initializer import _MCPToolInitializer
from quickapp.mcp_tooling._mcp_tooling_context import _MCPToolingContext
from quickapp.mcp_tooling._mcp_toolset_client import _MCPToolsetClient
from quickapp.mcp_tooling._read_mcp_resource_tool import (
    READ_MCP_RESOURCE_TOOL_CONFIG,
    _ReadMcpResourceTool,
)

logger = logging.getLogger(__name__)


class MCPToolingModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(_MCPToolInitializer, to=_MCPToolInitializer, scope=request_scope)
        binder.bind(_MCPToolingContext, to=_MCPToolingContext, scope=request_scope)
        binder.bind(_MCPStageWrapper, to=_MCPStageWrapper, scope=request_scope)
        binder.bind(_MCPTool, to=_MCPTool, scope=request_scope)
        binder.bind(_MCPToolsetClient, to=_MCPToolsetClient, scope=request_scope)
        binder.bind(_MCPSessionManager, to=_MCPSessionManager, scope=request_scope)
        binder.bind(DialToolsetCacheService, to=DialToolsetCacheService, scope=singleton)
        binder.bind(_MCPResourceCardProvider, to=_MCPResourceCardProvider, scope=request_scope)
        binder.bind(
            _MCPEagerResourceTransformer, to=_MCPEagerResourceTransformer, scope=request_scope
        )
        binder.bind(_ReadMcpResourceTool, to=_ReadMcpResourceTool, scope=request_scope)
        logger.debug("MCPToolingModule module configuration completed")

    @staticmethod
    def _has_resources(app_config: ApplicationConfig) -> bool:
        return any(
            isinstance(ts, (MCPToolSet, DialMCPToolSet))
            and ts.resources is not None
            and ts.resources.enabled
            for ts in (app_config.tool_sets or [])
        )

    @multiprovider
    def __provide_mcp_toolsets(
        self, app_config: ApplicationConfig
    ) -> list[MCPToolSet | DialMCPToolSet]:
        return [
            toolset_info
            for toolset_info in (app_config.tool_sets or [])
            if isinstance(toolset_info, (MCPToolSet, DialMCPToolSet))
        ]

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_MCPToolInitializer]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def _provide_mcp_tools(self, mcp_context: _MCPToolingContext) -> list[StagedBaseTool]:
        return mcp_context.tools

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _MCPToolingContext
    ) -> list[InitializationException]:
        return context.exceptions

    @multiprovider
    def _provide_prompt_parts(
        self, app_config: ApplicationConfig, card_provider: _MCPResourceCardProvider
    ) -> list[PromptPartProvider]:
        if not self._has_resources(app_config):
            return []
        return [card_provider]

    @multiprovider
    def _provide_message_transformers(
        self, app_config: ApplicationConfig, transformer: _MCPEagerResourceTransformer
    ) -> list[MessagesTransformer]:
        if not self._has_resources(app_config):
            return []
        return [transformer]

    @multiprovider
    def _provide_read_resource_tool(
        self,
        app_config: ApplicationConfig,
        tool_builder: AssistedBuilder[_ReadMcpResourceTool],
    ) -> list[StagedBaseTool]:
        """Conditionally provide read_mcp_resource only when at least one toolset enables resources."""
        if not self._has_resources(app_config):
            return []
        return [
            tool_builder.build(
                tool_config=READ_MCP_RESOURCE_TOOL_CONFIG,
                name=INTERNAL_MCP_READ_RESOURCE_TOOL_NAME,
                description=READ_MCP_RESOURCE_TOOL_CONFIG.open_ai_tool.function.description,
            )
        ]
