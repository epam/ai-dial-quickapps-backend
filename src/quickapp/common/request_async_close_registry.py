import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class RequestAsyncCloseRegistry:
    """Request-scoped registry of async teardown callbacks.

    Lets request-scoped resources that hold an async context open for the whole
    request (e.g. live MCP sessions) register a coroutine to be awaited once, at
    request end. The orchestrator flushes this from its ``_persisting_state()``
    ``finally`` block, so cleanup runs on both the success and the error path.

    Mirrors ``DeferredStageCloseRegistry``: failures are logged and swallowed so a
    misbehaving resource cannot break teardown of the others or mask the original
    error being re-raised.
    """

    def __init__(self) -> None:
        self._closers: list[tuple[str, Callable[[], Awaitable[None]]]] = []

    def register(self, name: str, aclose: Callable[[], Awaitable[None]]) -> None:
        self._closers.append((name, aclose))

    async def aclose_all(self) -> None:
        closers = self._closers
        self._closers = []
        for name, aclose in closers:
            try:
                await aclose()
            except Exception:
                logger.exception("Failed while closing async resource '%s'", name)
