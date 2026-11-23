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

    Background work that outlives the request shares the teardown with ``hand_off``. The
    registry counts shares: the request holds one (released by ``aclose_all``) and every hand-off
    adds one. The closers run when the last share is released, whichever owner that is.
    """

    def __init__(self) -> None:
        self._closers: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        self._shares = 1
        self._request_share_released = False

    def register(self, name: str, aclose: Callable[[], Awaitable[None]]) -> None:
        self._closers.append((name, aclose))

    def hand_off(self) -> Callable[[], Awaitable[None]]:
        """Take a share of the teardown and return the callable that releases it (once)."""
        self._shares += 1
        released = False

        async def _release() -> None:
            nonlocal released
            if released:
                return
            released = True
            await self._release_share()

        return _release

    async def aclose_all(self) -> None:
        """Release the request's own share; the closers run if no hand-off still holds one."""
        if self._request_share_released:
            return
        self._request_share_released = True
        await self._release_share()

    async def _release_share(self) -> None:
        self._shares -= 1
        if self._shares == 0:
            await self._run_closers()

    async def _run_closers(self) -> None:
        closers = self._closers
        self._closers = []
        for name, aclose in closers:
            try:
                await aclose()
            except Exception:
                logger.exception("Failed while closing async resource '%s'", name)
