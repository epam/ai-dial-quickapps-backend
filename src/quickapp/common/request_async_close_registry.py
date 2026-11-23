import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Strong references to teardown tasks that outlive their request (otherwise they can be GC'd).
_DEFERRED_CLOSE_TASKS: set[asyncio.Task[None]] = set()


class RequestAsyncCloseRegistry:
    """Request-scoped registry of async teardown callbacks.

    Lets request-scoped resources that hold an async context open for the whole
    request (e.g. live MCP sessions) register a coroutine to be awaited once, at
    request end. The orchestrator flushes this from its ``_persisting_state()``
    ``finally`` block, so cleanup runs on both the success and the error path.

    Mirrors ``DeferredStageCloseRegistry``: failures are logged and swallowed so a
    misbehaving resource cannot break teardown of the others or mask the original
    error being re-raised.

    Detached work (async hooks) is tracked with ``track_detached``. While any is still running,
    ``aclose_all`` does not block the request: the teardown is deferred to a background task that
    runs the closers once the detached work has finished.
    """

    def __init__(self) -> None:
        self._closers: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        self._detached: set[asyncio.Task] = set()

    def register(self, name: str, aclose: Callable[[], Awaitable[None]]) -> None:
        self._closers.append((name, aclose))

    def track_detached(self, task: asyncio.Task) -> None:
        self._detached.add(task)
        task.add_done_callback(self._detached.discard)

    async def aclose_all(self) -> None:
        closers = self._closers
        self._closers = []
        pending = {task for task in self._detached if not task.done()}
        if pending:
            logger.info("Deferring request teardown until %d detached task(s) finish", len(pending))
            task = asyncio.create_task(self._close_after(pending, closers))
            _DEFERRED_CLOSE_TASKS.add(task)
            task.add_done_callback(_DEFERRED_CLOSE_TASKS.discard)
            return
        await self._run_closers(closers)

    async def _close_after(
        self, pending: set[asyncio.Task], closers: list[tuple[str, Callable[[], Awaitable[None]]]]
    ) -> None:
        await asyncio.gather(*pending, return_exceptions=True)
        await self._run_closers(closers)
        logger.info("Deferred request teardown completed")

    @staticmethod
    async def _run_closers(closers: list[tuple[str, Callable[[], Awaitable[None]]]]) -> None:
        for name, aclose in closers:
            try:
                await aclose()
            except Exception:
                logger.exception("Failed while closing async resource '%s'", name)
