import logging
import time
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')
LONG_CACHE_TTL: float = 1200  # 20 minutes
SHORT_CACHE_TTL: float = 300  # 5 minutes


class CacheEntry(Generic[T]):
    def __init__(self, value: T, ttl: float):
        self.value = value
        self.expiry = time.time() + ttl

    def is_expired(self) -> bool:
        return time.time() > self.expiry


class Cache(Generic[T]):
    def __init__(self):
        self._store: dict[str, CacheEntry[T]] = {}

    def get(self, key) -> CacheEntry[T] | None:
        return self._store.get(key, None)

    def put(self, key, entry: CacheEntry):
        self._store[key] = entry


class CacheService(Generic[T]):
    def __init__(self, ttl: float = LONG_CACHE_TTL):
        self._cache: Cache[T] = Cache[T]()
        self._ttl: float = ttl

    async def get(
        self, key: str, loader: Callable[..., Awaitable[T | None]], *args, **kwargs
    ) -> T | None:
        entry = self._cache.get(key)
        if entry is not None and not entry.is_expired():
            logger.debug(f"{key} value loaded from cache")
            return entry.value
        # Load new value because expired or missing
        value = await loader(*args, **kwargs)
        if value is None:
            logger.warning(f"Loader return None for {key}. None can't be cached.")
            return None
        logger.debug(f"{key} value loaded and updated in cache")
        self._cache.put(key, CacheEntry(value, self._ttl))
        return value
