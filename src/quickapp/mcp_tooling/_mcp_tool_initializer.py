import asyncio
import logging
from typing import Any
from urllib.parse import unquote

import httpx
from aidial_client import ToolsetInfo
from injector import AssistedBuilder, ProviderOf, inject
from mcp.shared.exceptions import McpError

from quickapp.common import DIAL_API_KEY, StagedBaseTool
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import ToolInitializationException
from quickapp.common.json_schema_converter import JsonSchemaConverter
from quickapp.common.utils import sanitize_toolname
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
from quickapp.dial_core_services._interactive_login_service import InteractiveLoginService
from quickapp.dial_core_services._login_result import LoginResult
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

from ._di_types import DialToolsetCacheService
from ._mcp_connection_manager import _MCPConnectionManager
from ._mcp_tool import _MCPTool
from ._mcp_tooling_context import _MCPToolingContext
from ._mcp_unauthorized_exception import MCPUnauthorizedException

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


def _flatten_exceptions(exc: BaseException) -> list[BaseException]:
    """Walk nested BaseExceptionGroups and return their leaf exceptions in order."""
    if isinstance(exc, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for sub in exc.exceptions:
            leaves.extend(_flatten_exceptions(sub))
        return leaves
    return [exc]


def _format_leaf_for_user(label: str, exc: BaseException) -> str:
    """Render a leaf exception into a single-line user-facing message."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = getattr(exc.response, "status_code", "")
        reason = getattr(exc.response, "reason_phrase", "")
        return f"HTTP error for {label}: {status} {reason}".rstrip()
    if isinstance(exc, McpError):
        # The MCP streamable_http client converts upstream HTTP 404 into
        # McpError("Session terminated") (mcp/client/streamable_http.py),
        # so the underlying httpx error never propagates. Surface this case
        # distinctly instead of leaking the raw "Session terminated" string.
        message = exc.error.message
        if message == "Session terminated":
            return (
                f"MCP endpoint for toolset '{label}' did not respond as an MCP server "
                f"(session terminated — the upstream may have returned 404)"
            )
        return f"MCP error for {label}: {message}"
    return f"{type(exc).__name__}: {exc}"


_LOGIN_RESULT_MESSAGES: dict[LoginResult, str] = {
    LoginResult.NO_CHANNEL: "Toolset '{name}' requires sign-in, but no client channel is available",
    LoginResult.DENIED: "Sign-in was denied for toolset '{name}'",
    LoginResult.TIMEOUT: "Sign-in timed out for toolset '{name}'",
    LoginResult.ERROR: "Sign-in failed for toolset '{name}'",
}


def _login_result_message(result: LoginResult, toolset_label: str) -> str:
    template = _LOGIN_RESULT_MESSAGES.get(result, "Sign-in failed for toolset '{name}'")
    return template.format(name=toolset_label)


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
        toolset_list_provider: ProviderOf[list[MCPToolSet | DialMCPToolSet]],
        mcp_context: _MCPToolingContext,
        dial_setting: DialSettings,
        api_key_provider: ProviderOf[DIAL_API_KEY],
        tool_builder: AssistedBuilder[_MCPTool],
        connection_manager_builder: AssistedBuilder[_MCPConnectionManager],
        dial_mcp_cache: DialToolsetCacheService,
        tool_config_service: ToolConfigCoreService,
        login_service: InteractiveLoginService,
    ):
        # Resolved lazily in initialize() because dial_app_tooling contributes
        # to this multibinder only after _DialAppResolver runs.
        self.__toolset_list_provider: ProviderOf[list[MCPToolSet | DialMCPToolSet]] = (
            toolset_list_provider
        )
        self.__mcp_context: _MCPToolingContext = mcp_context
        self.__dial_setting: DialSettings = dial_setting
        self.__api_key_provider: ProviderOf[DIAL_API_KEY] = api_key_provider
        self.__tool_builder: AssistedBuilder[_MCPTool] = tool_builder
        self.__connection_manager_builder: AssistedBuilder[_MCPConnectionManager] = (
            connection_manager_builder
        )
        self.__mcp_cache: DialToolsetCacheService = dial_mcp_cache
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__login_service: InteractiveLoginService = login_service

    @staticmethod
    # todo add Title to config so that we could use it in stage name
    def _convert_to_openai_tool(
        name: str, description: str | None, input_schema: dict[str, Any]
    ) -> OpenAiToolConfig:
        return OpenAiToolConfig(
            function=OpenAiToolFunction(
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
        toolsets = self.__toolset_list_provider.get()
        if not toolsets:
            return

        tasks = [asyncio.create_task(self._process_toolset(ts)) for ts in toolsets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        unauthorized = self._classify_initialization_results(toolsets, results)
        if not unauthorized:
            return

        await self._interactive_login_and_retry(unauthorized)

    def _classify_initialization_results(
        self,
        toolsets: list[MCPToolSet | DialMCPToolSet],
        results: list[BaseException | None],
    ) -> list[DialMCPToolSet]:
        """Collect unauthorized DialMCPToolSets for interactive login, record other errors."""
        unauthorized: list[DialMCPToolSet] = []
        for ts, result in zip(toolsets, results):
            if isinstance(result, MCPUnauthorizedException) and isinstance(ts, DialMCPToolSet):
                unauthorized.append(ts)
            elif isinstance(result, MCPUnauthorizedException):
                label = _toolset_label_for_error(ts)
                logger.error(
                    "MCP toolset '%s' returned 401 (not eligible for interactive login)", label
                )
                self.__mcp_context.append_exception(
                    ToolInitializationException(
                        message=f"Authentication required for toolset '{label}'",
                        toolset_name=label,
                    )
                )
            elif isinstance(result, Exception):
                logger.error("Unexpected error during MCP toolset initialization", exc_info=result)
        return unauthorized

    async def _interactive_login_and_retry(self, unauthorized: list[DialMCPToolSet]) -> None:
        """Batch interactive login for unauthorized toolsets, then retry successful ones."""
        dial_ids = [ts.dial_id for ts in unauthorized]
        signin_results = await self.__login_service.request_signin_batch(dial_ids)

        retry_toolsets: list[DialMCPToolSet] = []
        for ts in unauthorized:
            login_result = signin_results.get(ts.dial_id, LoginResult.ERROR)
            if login_result == LoginResult.SUCCESS:
                retry_toolsets.append(ts)
            else:
                label = _toolset_label_for_error(ts)
                self.__mcp_context.append_exception(
                    ToolInitializationException(
                        message=_login_result_message(login_result, label),
                        toolset_name=label,
                    )
                )

        if retry_toolsets:
            retry_tasks = [
                asyncio.create_task(self._retry_process_toolset(ts)) for ts in retry_toolsets
            ]
            await asyncio.gather(*retry_tasks)

    async def _retry_process_toolset(self, toolset_info: DialMCPToolSet) -> None:
        """Retry _process_toolset after successful interactive login.

        Catches all exceptions (including MCPUnauthorizedException) and converts them to
        ToolInitializationException, since interactive login was already attempted.
        """
        label = _toolset_label_for_error(toolset_info)
        try:
            await self._process_toolset(toolset_info)
        except Exception as e:
            logger.error("Toolset '%s' failed after interactive login: %s", label, e, exc_info=True)
            self.__mcp_context.append_exception(
                ToolInitializationException(
                    message=f"Sign-in succeeded but toolset '{label}' initialization still failed",
                    toolset_name=label,
                    details=str(e),
                )
            )

    async def _process_toolset(self, toolset_info: MCPToolSet | DialMCPToolSet) -> None:
        if not toolset_info.enabled:
            return

        resolved_toolset: MCPToolSet | DialMCPToolSet = toolset_info
        try:
            # Resolve DialMCPToolSet data asynchronously if needed
            if isinstance(toolset_info, DialMCPToolSet):
                dial_toolset_info: ToolsetInfo | None = await self.__mcp_cache.get(
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
                            if (dial_toolset_info.transport or "").lower() == "sse"
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
                            sanitize_toolname(f"{resolved_toolset.name}_{tool.name}"),
                            tool.description,
                            tool.inputSchema,
                        ),
                    ),
                    connection_manager=connection_manager,
                    dial_toolset_id=(
                        toolset_info.dial_id if isinstance(toolset_info, DialMCPToolSet) else None
                    ),
                )
                created_tools.append(mcp_tool)
            if created_tools:
                self.__mcp_context.extend_tools(created_tools)

        except MCPUnauthorizedException:
            raise
        except ToolInitializationException as e:
            logger.error(e, exc_info=True)
            self.__mcp_context.append_exception(e)
        except httpx.HTTPStatusError as e:
            label = _toolset_label_for_error(toolset_info)
            logger.error(f"HTTP error: {e}", exc_info=True)
            self.__mcp_context.append_exception(
                ToolInitializationException(
                    message=_format_leaf_for_user(label, e),
                    toolset_name=label,
                )
            )
        except Exception as e:
            label = _toolset_label_for_error(toolset_info)
            logger.error(e, exc_info=True)
            detail_lines = [_format_leaf_for_user(label, leaf) for leaf in _flatten_exceptions(e)]
            self.__mcp_context.append_exception(
                ToolInitializationException(
                    message=detail_lines[0],
                    toolset_name=label,
                    details="\n".join(detail_lines),
                )
            )
