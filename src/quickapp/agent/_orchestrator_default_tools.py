"""Orchestrator default tools: cache and service to merge deployment defaults.tools with app tools."""

import logging
from typing import Any

from injector import ProviderOf, inject
from pydantic import SecretStr

from aidial_sdk.chat_completion.request import StaticTool

from quickapp.common import DIAL_API_KEY
from quickapp.common.cache import CacheService, LONG_CACHE_TTL
from quickapp.common.dial_core_client import DialCoreClient
from quickapp.common.dial_settings import DialSettings

logger = logging.getLogger(__name__)

STATIC_FUNCTION_TYPE = "static_function"
DEFAULTS_TOOLS_KEY = "defaults"
TOOLS_KEY = "tools"
TYPE_KEY = "type"


class OrchestratorDefaultToolsCacheService(CacheService[list[dict[str, Any]]]):
    """Cache for deployment default tools (list of request-shape dicts). Keyed by deployment name."""

    def __init__(self, ttl: float = LONG_CACHE_TTL) -> None:
        super().__init__(ttl=ttl)


def _parse_default_tools_from_info(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract and parse defaults.tools from deployment info into request-shape dicts.

    Supports type == "static_function"; other types are skipped with a debug log.
    Returns empty list if defaults or defaults.tools are missing.
    """
    defaults = info.get(DEFAULTS_TOOLS_KEY)
    if not isinstance(defaults, dict):
        return []
    raw_tools = defaults.get(TOOLS_KEY)
    if not isinstance(raw_tools, list):
        return []
    result: list[dict[str, Any]] = []
    for entry in raw_tools:
        if not isinstance(entry, dict):
            continue
        tool_type = entry.get(TYPE_KEY)
        if tool_type == STATIC_FUNCTION_TYPE:
            try:
                static_tool = StaticTool.parse_obj(entry)
                # Pydantic v1: use .dict(); exclude_none for clean payload
                out = static_tool.dict(exclude_none=True)
                result.append(out)
            except Exception:
                logger.debug(
                    "Skipping invalid static_function entry in defaults.tools: %s",
                    entry,
                    exc_info=True,
                )
        else:
            logger.debug(
                "Skipping unsupported default tool type: %s (deployment defaults.tools)",
                tool_type,
            )
    return result


async def load_default_tools_for_deployment(
    deployment: str,
    dial_settings: DialSettings,
    api_key: SecretStr | str,
) -> list[dict[str, Any]] | None:
    """Async loader: fetch deployment info from DIAL Core and return parsed default tools.

    Returns list of request-shape dicts on success (empty if no defaults.tools).
    Returns None on failure so the cache does not store failures.
    """
    try:
        async with DialCoreClient(
            api_key=api_key,
            base_url=dial_settings.url,
        ) as dial_core:
            info = await dial_core.get_deployment_info(deployment)
            return _parse_default_tools_from_info(info)
    except Exception:
        logger.debug(
            "Failed to load default tools for deployment %s",
            deployment,
            exc_info=True,
        )
        return None


@inject
class OrchestratorDefaultToolsService:
    """Provides default tools for an orchestrator deployment via cache and DIAL Core."""

    def __init__(
        self,
        cache: OrchestratorDefaultToolsCacheService,
        dial_settings: DialSettings,
        api_key_provider: ProviderOf[DIAL_API_KEY],
    ) -> None:
        self.__cache = cache
        self.__dial_settings = dial_settings
        self.__api_key_provider = api_key_provider

    async def get_default_tools(self, deployment: str) -> list[dict[str, Any]]:
        """Return default tools for the deployment (cached). Empty list on failure or missing."""
        api_key = self.__api_key_provider.get()

        async def loader(deploy: str) -> list[dict[str, Any]] | None:
            return await load_default_tools_for_deployment(
                deploy,
                self.__dial_settings,
                api_key,
            )

        value = await self.__cache.get(deployment, loader, deployment)
        return value if value is not None else []
