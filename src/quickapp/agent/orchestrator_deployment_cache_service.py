from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment

from quickapp.common.cache import CacheService


class OrchestratorDeploymentCacheService(CacheService[Deployment | Application]):
    """Cache for orchestrator deployment metadata.

    Held separately from :class:`DialDeploymentToolCacheService` so that orchestrator
    capability lookups can evict independently of deployment-tool config caching, and
    so neither path can starve the other on TTL renewal.
    """
