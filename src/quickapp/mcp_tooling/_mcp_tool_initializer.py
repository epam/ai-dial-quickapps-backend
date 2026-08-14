import asyncio
import logging
from typing import Any
from urllib.parse import unquote

import httpx
from aidial_client import ToolsetInfo
from injector import AssistedBuilder, ProviderOf, inject
from mcp.shared.exceptions import McpError
from mcp.types import BlobResourceContents, TextResourceContents

from quickapp.common import DIAL_API_KEY, AcceptLanguage, StagedBaseTool
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import ToolInitializationException
from quickapp.common.json_schema_converter import JsonSchemaConverter
from quickapp.common.localized_string import resolve_localized
from quickapp.common.utils import posix_path_last_segment, sanitize_toolname
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
from quickapp.mcp_tooling._mcp_eager_resource import MCPEagerTextResource
from quickapp.mcp_tooling._mcp_resource_meta import MCPResourceMeta
from quickapp.mcp_tooling._mcp_server_capabilities import MCPServerCapabilities

from ._di_types import DialToolsetCacheService
from ._mcp_tool import _MCPTool
from ._mcp_tooling_context import _MCPToolingContext
from ._mcp_toolset_client import _MCPToolsetClient
from ._mcp_unauthorized_exception import MCPUnauthorizedException

logger = logging.getLogger(__name__)

# Default name when UI doesn't send toolset name; must match DialMCPToolSet.name default
_UNTITLED_MCP_TOOLSET = DialMCPToolSet.model_fields["name"].default


def _human_readable_dial_id(dial_id: str) -> str:
    """Extract a human-readable label from a DIAL toolset id.
    E.g. 'toolsets/684f6.../TestMCP__0.0.1' or 'toolsets/TestMCP__0.0.1' -> 'TestMCP__0.0.1'.
    URL-decodes the result to convert %20 to spaces and other encoded characters.
    """
    return unquote(posix_path_last_segment(dial_id))


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


def _toolset_key(toolset_info: MCPToolSet | DialMCPToolSet) -> str:
    """Stable per-app key identifying a toolset's session across calls (and, later, turns).

    DialMCPToolSet keys on its canonical ``deployment_id``; a directly-addressed MCPToolSet
    keys on its ``name``. Prefixed so a deployment id can never collide with a plain name.
    """
    if isinstance(toolset_info, DialMCPToolSet):
        return f"dial:{toolset_info.deployment_id}"
    return f"mcp:{resolve_localized(toolset_info.name)}"


def _toolset_label_for_error(toolset_info: MCPToolSet | DialMCPToolSet) -> str:
    """Return a label for this toolset suitable for error messages.
    For DialMCPToolSet with default name, use a human-readable form of deployment_id.
    """
    if isinstance(toolset_info, DialMCPToolSet) and toolset_info.name == _UNTITLED_MCP_TOOLSET:
        return _human_readable_dial_id(toolset_info.deployment_id)
    return resolve_localized(getattr(toolset_info, "name", ""))


@inject
class _MCPToolInitializer(CompletionInitializer):
    def __init__(
        self,
        toolset_list_provider: ProviderOf[list[MCPToolSet | DialMCPToolSet]],
        mcp_context: _MCPToolingContext,
        dial_setting: DialSettings,
        api_key_provider: ProviderOf[DIAL_API_KEY],
        tool_builder: AssistedBuilder[_MCPTool],
        toolset_client_builder: AssistedBuilder[_MCPToolsetClient],
        dial_mcp_cache: DialToolsetCacheService,
        tool_config_service: ToolConfigCoreService,
        login_service: InteractiveLoginService,
        accept_language: AcceptLanguage,
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
        self.__toolset_client_builder: AssistedBuilder[_MCPToolsetClient] = toolset_client_builder
        self.__mcp_cache: DialToolsetCacheService = dial_mcp_cache
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__login_service: InteractiveLoginService = login_service
        self.__accept_language: AcceptLanguage = accept_language

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
        deployment_ids = [ts.deployment_id for ts in unauthorized]
        signin_results = await self.__login_service.request_signin_batch(deployment_ids)

        retry_toolsets: list[DialMCPToolSet] = []
        for ts in unauthorized:
            login_result = signin_results.get(ts.deployment_id, LoginResult.ERROR)
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

    async def _load_tools(
        self,
        resolved_toolset: MCPToolSet,
        toolset_info: MCPToolSet | DialMCPToolSet,
        toolset_client: _MCPToolsetClient,
        session: Any,
    ) -> None:
        tools = await toolset_client.get_tools_list(session)

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
                        sanitize_toolname(f"{resolve_localized(resolved_toolset.name)}_{tool.name}"),
                        tool.description,
                        tool.inputSchema,
                    ),
                ),
                toolset_client=toolset_client,
                dial_toolset_id=(
                    toolset_info.deployment_id if isinstance(toolset_info, DialMCPToolSet) else None
                ),
            )
            mcp_tool.stage_name_component = resolve_localized(
                resolved_toolset.name, self.__accept_language
            )
            created_tools.append(mcp_tool)
        if created_tools:
            self.__mcp_context.extend_tools(created_tools)

    async def _load_resources(
        self,
        resolved_toolset: MCPToolSet,
        toolset_client: _MCPToolsetClient,
        session: Any,
    ) -> None:
        assert resolved_toolset.resources is not None
        resources_config = resolved_toolset.resources

        server_resources = await toolset_client.get_resources_list(session)

        # Filter to configured items when an explicit list is provided
        if resources_config.items is not None:
            allowed_uris = {item.uri for item in resources_config.items}
            server_resources = [r for r in server_resources if str(r.uri) in allowed_uris]

        metas: list[MCPResourceMeta] = []
        for resource in server_resources:
            metas.append(
                MCPResourceMeta(
                    toolset_name=resolved_toolset.name,
                    toolset_description=resolved_toolset.description,
                    resource_name=resource.name,
                    resource_uri=str(resource.uri),
                    resource_description=resource.description,
                    mime_type=resource.mimeType,
                )
            )
        if metas:
            self.__mcp_context.extend_resource_metas(metas)

        # Load eager resources
        if resources_config.items is None:
            return

        for item in resources_config.items:
            if not item.eager:
                continue
            try:
                contents = await toolset_client.read_resource_contents(session, item.uri)
                for content in contents:
                    if isinstance(content, TextResourceContents):
                        meta = next(
                            (m for m in metas if m.resource_uri == item.uri),
                            None,
                        )
                        if meta is None:
                            logger.warning(
                                "Eager resource '%s' in toolset '%s' was configured as eager "
                                "but not returned by the server — skipping",
                                item.uri,
                                resolved_toolset.name,
                            )
                            continue
                        self.__mcp_context.extend_eager_resources(
                            [
                                MCPEagerTextResource(
                                    toolset_name=meta.toolset_name,
                                    toolset_description=meta.toolset_description,
                                    resource_name=meta.resource_name,
                                    resource_uri=meta.resource_uri,
                                    resource_description=meta.resource_description,
                                    mime_type=meta.mime_type,
                                    text=content.text,
                                )
                            ]
                        )
                    elif isinstance(content, BlobResourceContents):
                        logger.warning(
                            "Eager resource '%s' in toolset '%s' is a blob — skipping (Phase 2)",
                            item.uri,
                            resolved_toolset.name,
                        )
            except Exception as e:
                label = resolved_toolset.name
                logger.error(
                    "Failed to read eager resource '%s' for toolset '%s': %s",
                    item.uri,
                    label,
                    e,
                    exc_info=True,
                )
                self.__mcp_context.append_exception(
                    ToolInitializationException(
                        message=f"Failed to load eager resource '{item.uri}' for toolset '{label}'",
                        toolset_name=label,
                        details=str(e),
                    )
                )

    async def _process_toolset(self, toolset_info: MCPToolSet | DialMCPToolSet) -> None:
        if not toolset_info.enabled:
            return

        try:
            # Resolve DialMCPToolSet to a plain MCPToolSet before any session work
            if isinstance(toolset_info, DialMCPToolSet):
                dial_toolset_info: ToolsetInfo | None = await self.__mcp_cache.get(
                    f"mcp_toolset_{toolset_info.deployment_id}",
                    self.__tool_config_service.get_basic_toolset_config,
                    toolset_info.deployment_id,
                )
                if not dial_toolset_info:
                    raise ToolInitializationException(
                        message=f"Failed to retrieve toolset info for DIAL ID {toolset_info.deployment_id}",
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
                        url=f"{self.__dial_setting.url}/v1/toolset/{toolset_info.deployment_id}/mcp",
                        authorization=MCPApiKeyAuthorization(
                            key=self.__api_key_provider.get().get_secret_value(), name="Api-Key"
                        ),
                        protocol=(
                            MCPProtocol.sse
                            if (dial_toolset_info.transport or "").lower() == "sse"
                            else MCPProtocol.streamable_http
                        ),
                    ),
                    resources=toolset_info.resources,
                )
            else:
                resolved_toolset = toolset_info

            toolset_client = self.__toolset_client_builder.build(
                toolset_info=resolved_toolset,
                toolset_key=_toolset_key(toolset_info),
            )

            async with toolset_client.open_init_session() as (session, init_result):
                # Capture server capabilities
                caps = MCPServerCapabilities(
                    toolset_name=resolved_toolset.name,
                    server_name=init_result.serverInfo.name,
                    server_version=init_result.serverInfo.version or "",
                    protocol_version=str(init_result.protocolVersion),
                    supports_tools=init_result.capabilities.tools is not None,
                    supports_resources=init_result.capabilities.resources is not None,
                    supports_prompts=init_result.capabilities.prompts is not None,
                )
                self.__mcp_context.extend_server_capabilities([caps])

                # Tool loading — independent error scope
                label = _toolset_label_for_error(toolset_info)
                try:
                    if caps.supports_tools:
                        await self._load_tools(
                            resolved_toolset, toolset_info, toolset_client, session
                        )
                    else:
                        logger.warning(
                            "Toolset '%s' server does not advertise tools capability — skipping tool list",
                            label,
                        )
                except MCPUnauthorizedException:
                    raise
                except Exception as e:
                    logger.error(
                        "Tool loading failed for toolset '%s': %s", label, e, exc_info=True
                    )
                    detail_lines = [
                        _format_leaf_for_user(label, leaf) for leaf in _flatten_exceptions(e)
                    ]
                    self.__mcp_context.append_exception(
                        ToolInitializationException(
                            message=detail_lines[0],
                            toolset_name=label,
                            details="\n".join(detail_lines),
                        )
                    )

                # Resource loading — independent error scope
                if resolved_toolset.resources and resolved_toolset.resources.enabled:
                    if caps.supports_resources:
                        try:
                            await self._load_resources(resolved_toolset, toolset_client, session)
                        except MCPUnauthorizedException:
                            raise
                        except Exception as e:
                            logger.error(
                                "Resource loading failed for toolset '%s': %s",
                                label,
                                e,
                                exc_info=True,
                            )
                            self.__mcp_context.append_exception(
                                ToolInitializationException(
                                    message=f"Failed to load resources for toolset '{label}'",
                                    toolset_name=label,
                                    details=str(e),
                                )
                            )
                    else:
                        logger.warning(
                            "Toolset '%s' has resources.enabled=true but server does not "
                            "advertise resources capability — skipping",
                            label,
                        )

            # Register client for on-demand resource reads by _ReadMcpResourceTool
            self.__mcp_context.register_client(resolved_toolset.name, toolset_client)

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
