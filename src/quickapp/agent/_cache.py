from typing import Any

from aidial_client.types.deployment import Deployment

from quickapp.common.cache import CacheService, LONG_CACHE_TTL


class OrchestratorDefaultToolsCacheService(CacheService[list[dict[str, Deployment]]]):
    """Cache for deployment default tools (list of request-shape dicts). Keyed by deployment name."""

    def __init__(self, ttl: float = LONG_CACHE_TTL) -> None:
        super().__init__(ttl=ttl)
