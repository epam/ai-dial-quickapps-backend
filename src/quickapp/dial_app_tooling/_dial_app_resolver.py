import asyncio
import logging

from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment
from injector import ProviderOf, inject

from quickapp.common import DIAL_API_KEY
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.deployment_tool_cache import DialDeploymentToolCacheService
from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.application import ApplicationConfig
from quickapp.config.toolsets.authorization import MCPApiKeyAuthorization
from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

from ._dial_app_resolver_context import _DialAppResolverContext

logger = logging.getLogger(__name__)


@inject
class _DialAppResolver(CompletionInitializer):
    """Expands each DialAppToolSet into transport-specific inputs consumed by
    _MCPToolInitializer and _DeploymentToolInitializer. Declares a negative
    ``order`` so it runs before its consumers, which then read the populated
    ``_DialAppResolverContext`` directly. Request-scoped.
    """

    order = -100

    def __init__(
        self,
        app_config: ApplicationConfig,
        dial_settings: DialSettings,
        api_key_provider: ProviderOf[DIAL_API_KEY],
        tool_config_service: ToolConfigCoreService,
        deployment_cache: DialDeploymentToolCacheService,
        context: _DialAppResolverContext,
    ):
        self.__app_config: ApplicationConfig = app_config
        self.__dial_settings: DialSettings = dial_settings
        self.__api_key_provider: ProviderOf[DIAL_API_KEY] = api_key_provider
        self.__tool_config_service: ToolConfigCoreService = tool_config_service
        self.__deployment_cache: DialDeploymentToolCacheService = deployment_cache
        self.__context: _DialAppResolverContext = context
        # Errors are intentionally un-cached so a sibling toolset in the same group can retry.
        self.__metadata_memo: dict[str, Deployment | Application] = {}

    async def initialize(self) -> None:
        await self.resolve()

    async def resolve(self) -> None:
        # CacheService.get is not concurrency-safe, so members sharing a deployment_id
        # resolve serially within a group; distinct deployments still parallelize.
        groups: dict[str, list[DialAppToolSet]] = {}
        for ts in self.__app_config.tool_sets or []:
            if isinstance(ts, DialAppToolSet) and ts.enabled:
                groups.setdefault(ts.deployment_id, []).append(ts)
        if not groups:
            return
        await asyncio.gather(
            *(self._resolve_group(items) for items in groups.values()),
            return_exceptions=True,
        )

    async def _resolve_group(self, toolsets: list[DialAppToolSet]) -> None:
        for ts in toolsets:
            await self._resolve_one(ts)

    async def _resolve_one(self, toolset: DialAppToolSet) -> None:
        try:
            if toolset.transport == "chat-completion":
                await self._handle_chat_completion_branch(toolset)
                return
            if await self._is_mcp_advertised(toolset.deployment_id):
                self._handle_mcp_branch(toolset)
            elif toolset.transport == "mcp":
                raise ToolInitializationException(
                    message=(
                        f"transport=mcp requested but features.mcp is not advertised "
                        f"on {toolset.deployment_id}"
                    ),
                    toolset_name=toolset.name,
                )
            else:
                await self._handle_chat_completion_branch(toolset)
        except ToolInitializationException as e:
            logger.error(e, exc_info=True)
            self.__context.append_exception(e)
        except Exception as e:
            logger.error(e, exc_info=True)
            details = ""
            if hasattr(e, "exceptions"):
                details = "\n".join(str(sub_e) for sub_e in e.exceptions)
            self.__context.append_exception(
                ToolInitializationException(
                    message=str(e),
                    toolset_name=toolset.name,
                    details=details,
                )
            )

    async def _is_mcp_advertised(self, deployment_id: str) -> bool:
        if deployment_id not in self.__metadata_memo:
            self.__metadata_memo[deployment_id] = (
                await self.__tool_config_service.get_deployment_metadata(deployment_id)
            )
        metadata = self.__metadata_memo[deployment_id]
        return bool(metadata.features and metadata.features.mcp)

    def _handle_mcp_branch(self, toolset: DialAppToolSet) -> None:
        if toolset.conversation_mode and toolset.conversation_mode.resumable:
            logger.warning(
                "conversation_mode.resumable set on DialAppToolSet '%s' is ignored on the MCP "
                "branch (resumable sessions apply only to the chat-completion deployment tool).",
                toolset.name,
            )
        url = f"{self.__dial_settings.url}/v1/deployments/{toolset.deployment_id}/mcp"
        api_key = self.__api_key_provider.get()
        mcp_toolset = MCPToolSet(
            name=toolset.name,
            description=toolset.description,
            enabled=toolset.enabled,
            allowed_tools=toolset.allowed_tools,
            attachment=toolset.attachment,
            fallback_configuration=toolset.fallback_configuration,
            mcp_server_info=MCPServerInfo(
                url=url,
                authorization=MCPApiKeyAuthorization(
                    key=api_key.get_secret_value(), name="Api-Key"
                ),
                protocol=MCPProtocol.streamable_http,
            ),
        )
        self.__context.append_mcp_toolset(mcp_toolset)

    async def _handle_chat_completion_branch(self, toolset: DialAppToolSet) -> None:
        if toolset.allowed_tools:
            logger.warning(
                "allowed_tools set on DialAppToolSet '%s' is ignored on the chat-completion "
                "fallback branch (single synthetic tool).",
                toolset.name,
            )
        tool_config = await self.__deployment_cache.fetch_basic_tool_config(
            self.__tool_config_service.get_basic_tool_config,
            toolset.deployment_id,
            toolset_name=toolset.name,
        )
        customised = tool_config.model_copy(
            update={
                "attachment": toolset.attachment,
                "fallback_configuration": toolset.fallback_configuration,
                "conversation_mode": toolset.conversation_mode,
            }
        )
        self.__context.append_deployment_tool(customised)
