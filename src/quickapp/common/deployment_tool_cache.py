from quickapp.common.cache import CacheService
from quickapp.config.tools.deployment import DialDeploymentTool

# Lives in `common/` rather than `dial_deployment_tooling/` so other tooling modules can
# inject the cache without triggering an import cycle through the deployment-tooling package.

BASIC_CONFIG_CACHE_KEY_PREFIX = "basic_config_"


class DialDeploymentToolCacheService(CacheService[DialDeploymentTool]):
    pass
