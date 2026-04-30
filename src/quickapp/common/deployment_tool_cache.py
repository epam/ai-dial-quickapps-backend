from collections.abc import Awaitable, Callable

from quickapp.common.cache import CacheService
from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.tools.deployment import DialDeploymentTool

# Lives in `common/` rather than `dial_deployment_tooling/` so other tooling modules can
# inject the cache without triggering an import cycle through the deployment-tooling package.

_BASIC_CONFIG_CACHE_KEY_PREFIX = "basic_config_"


class DialDeploymentToolCacheService(CacheService[DialDeploymentTool]):
    pass


async def fetch_basic_tool_config(
    cache: DialDeploymentToolCacheService,
    loader: Callable[[str], Awaitable[DialDeploymentTool | None]],
    deployment_id: str,
    *,
    toolset_name: str = "",
) -> DialDeploymentTool:
    """Fetch a deployment's basic tool config through the shared cache, raising if absent.

    DialAppToolSet's chat-completion fallback and DialDeploymentSimpleTool both route
    through this helper so they share the same singleton cache entry per deployment_id.
    """
    tool_config = await cache.get(
        f"{_BASIC_CONFIG_CACHE_KEY_PREFIX}{deployment_id}",
        loader,
        deployment_id,
    )
    if tool_config is None:
        raise ToolInitializationException(
            message=f"No tool config for {deployment_id}",
            toolset_name=toolset_name,
        )
    return tool_config
