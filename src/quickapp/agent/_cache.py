from aidial_sdk.chat_completion.request import StaticTool

from quickapp.common.cache import LONG_CACHE_TTL, CacheService


class OrchestratorDefaultToolsCacheService(CacheService[list[StaticTool]]):
    """Cache for deployment default tools (parsed StaticTool list). Keyed by deployment name."""

    def __init__(self, ttl: float = LONG_CACHE_TTL) -> None:
        super().__init__(ttl=ttl)
