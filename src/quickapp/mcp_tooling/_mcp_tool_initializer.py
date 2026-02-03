import asyncio
import logging
from typing import Any, Optional
from urllib.parse import unquote

import httpx
from injector import AssistedBuilder, ProviderOf, inject

from quickapp.common import DIAL_API_KEY, StagedBaseTool
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.dial_core_client import ToolsetInfo
from quickapp.common.dial_settings import DialSettings
from quickapp.common.json_schema_converter import JsonSchemaConverter
from quickapp.common.tool_initialization_exception import ToolInitializationException
from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.mcp import MCPTool
from quickapp.config.toolsets.authorization import MCPApiKeyAuthorization
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

from ._di_types import DialToolsetCacheService
from ._mcp_connection_manager import _MCPConnectionManager
from ._mcp_tool import _MCPTool
from ._mcp_tooling_context import _MCPToolingContext

logger = logging.getLogger(__name__)

# Default name when UI doesn't send toolset name; must match DialMCPToolSet.name default
_UNTITLED_MCP_TOOLSET = DialMCPToolSet.model_fields["name"].default


def _human_readable_dial_id(dial_id: str) -> str:
    """Extract a human-readable label from a DIAL toolset id.
    E.g. 'toolsets/684f6.../TestMCP__0.0.1' or 'toolsets/TestMCP__0.0.1' -> 'TestMCP__0.0.1'.
    URL-decodes the result to convert %20 to spaces and other encoded characters.
    """
    last_part = dial_id.split("/")[-1] if "/" in dial_id else dial_id
    return unquote(last_part)


def _toolset_label_for_error(toolset_info: MCPToolSet | DialMCPToolSet) -> str:
    """Return a label for this toolset suitable for error messages.
    For DialMCPToolSet with default name, use a human-readable form of dial_id.
    """
    if isinstance(toolset_info, DialMCPToolSet) and toolset_info.name == _UNTITLED_MCP_TOOLSET:
        return _human_readable_dial_id(toolset_info.dial_id)
    return getattr(toolset_info, "name", "")


@inject
class _MCPToolInitializer(CompletionInitializer):
    def __init__(
        self,
        toolset_list: list[MCPToolSet | DialMCPToolSet],
        mcp_context: _MCPToolingContext,
        dial_setting: DialSettings,
        api_key_provider: ProviderOf[DIAL_API_KEY],
        tool_builder: AssistedBuilder[_MCPTool],
        connection_manager_builder: AssistedBuilder[_MCPConnectionManager],
        dial_mcp_cache: DialToolsetCacheService,
        tool_config_service: ToolConfigCoreService,
    ):
        self.__toolset_list: list[MCPToolSet | DialMCPToolSet] = toolset_list
        self.__mcp_context: _MCPToolingContext = mcp_context
        self.__dial_setting: DialSettings = dial_setting
        self.__api_key_provider: ProviderOf[DIAL_API_KEY] = api_key_provider
        self.__tool_builder: AssistedBuilder[_MCPTool] = tool_builder
        self.__connection_manager_builder: AssistedBuilder[_MCPConnectionManager] = (
            connection_manager_builder
        )
        self.__mcp_cache: DialToolsetCacheService = dial_mcp_cache
        self.__tool_config_service: ToolConfigCoreService = tool_config_service

    @staticmethod
    # todo add Title to config so that we could use it in stage name
    def _convert_to_openai_tool(name: str, description: str | None, input_schema: dict[str, Any]):
        return OpenAiToolConfig(
            function=OpenAiToolFunction.model_construct(  # model_construct to prevent double @model_validator execution for name
                name=name,
                description=description or name,
                parameters=OpenAiToolFunctionParameters(
                    type=JsonTypeEnum.object,
                    properties=JsonSchemaConverter.convert_schema_to_properties(input_schema),
                    required=input_schema.get('required', []),
                ),
            )
        )

    async def initialize(self) -> None:
        if not self.__toolset_list:
            return

        # Create worker tasks for all configured toolsets and run them concurrently.
        tasks = [asyncio.create_task(self._process_toolset(ts)) for ts in self.__toolset_list]
        # Await all tasks; errors are handled inside each task. Use return_exceptions=True to be robust.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Log any unexpected exceptions propagated (should be rare because we catch inside worker)
        for r in results:
            if isinstance(r, Exception):
                logger.error("Unexpected error during MCP toolset initialization", exc_info=r)

    async def _process_toolset(self, toolset_info: MCPToolSet | DialMCPToolSet) -> None:
        if not toolset_info.enabled:
            return

        resolved_toolset: MCPToolSet | DialMCPToolSet = toolset_info
        try:
            # Resolve DialMCPToolSet data asynchronously if needed
            if isinstance(toolset_info, DialMCPToolSet):
                dial_toolset_info: Optional[ToolsetInfo] = await self.__mcp_cache.get(
                    f"mcp_toolset_{toolset_info.dial_id}",
                    self.__tool_config_service.get_basic_toolset_config,
                    toolset_info.dial_id,
                )
                if not dial_toolset_info:
                    raise ToolInitializationException(
                        message=f"Failed to retrieve toolset info for DIAL ID {toolset_info.dial_id}",
                        toolset_name=_toolset_label_for_error(toolset_info),
                    )
                resolved_toolset = MCPToolSet(
                    name=dial_toolset_info.display_name or toolset_info.name,
                    description=dial_toolset_info.description,
                    enabled=toolset_info.enabled,
                    allowed_tools=toolset_info.allowed_tools,
                    attachment=toolset_info.attachment,
                    fallback_configuration=toolset_info.fallback_configuration,
                    mcp_server_info=MCPServerInfo(
                        url=f"{self.__dial_setting.url}/v1/toolset/{toolset_info.dial_id}/mcp",
                        authorization=MCPApiKeyAuthorization(
                            key=self.__api_key_provider.get().get_secret_value(), name="Api-Key"
                        ),
                        protocol=(
                            MCPProtocol.sse
                            if dial_toolset_info.transport.lower() == "sse"
                            else MCPProtocol.streamable_http
                        ),
                    ),
                )

            connection_manager = self.__connection_manager_builder.build(
                toolset_info=resolved_toolset
            )
            tools = await connection_manager.get_tools_list()

            if resolved_toolset.allowed_tools:
                tools = [tool for tool in tools if tool.name in resolved_toolset.allowed_tools]

            created_tools: list[StagedBaseTool] = []
            for tool in tools:
                mcp_tool = self.__tool_builder.build(
                    tool=tool,
                    tool_config=MCPTool(
                        attachment=resolved_toolset.attachment,
                        fallback_configuration=resolved_toolset.fallback_configuration,
                        open_ai_tool=self._convert_to_openai_tool(
                            tool.name, tool.description, tool.inputSchema
                        ),
                    ),
                    connection_manager=connection_manager,
                )
                created_tools.append(mcp_tool)
            if created_tools:
                self.__mcp_context.extend_tools(created_tools)

        except ToolInitializationException as e:
            logger.error(e, exc_info=True)
            self.__mcp_context.append_exception(e)
        except httpx.HTTPStatusError as e:
            label = _toolset_label_for_error(toolset_info)
            logger.error(f"HTTP error: {e}", exc_info=True)
            self.__mcp_context.append_exception(
                ToolInitializationException(
                    message=str(e),
                    toolset_name=label,
                    details=f"HTTP error for {label}: {getattr(e.response, 'status_code', '')} {getattr(e.response, 'reason_phrase', '')}",
                )
            )
        except Exception as e:
            label = _toolset_label_for_error(toolset_info)
            logger.error(e, exc_info=True)
            details = ""
            if hasattr(e, "exceptions"):
                details_list = []
                for sub_e in e.exceptions:
                    if isinstance(sub_e, httpx.HTTPStatusError):
                        details_list.append(
                            f"HTTP error for {label}: {getattr(sub_e.response, 'status_code', '')} {getattr(sub_e.response, 'reason_phrase', '')}"
                        )
                    else:
                        details_list.append(str(sub_e))
                details = "\n".join(details_list)
            self.__mcp_context.append_exception(
                ToolInitializationException(
                    message=str(e),
                    toolset_name=label,
                    details=details,
                )
            )
