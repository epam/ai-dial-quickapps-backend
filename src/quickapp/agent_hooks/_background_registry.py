import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine, Sequence

from injector import inject

from quickapp.agent_hooks._background_hook_settings import BackgroundHookSettings
from quickapp.common.base_initializer import ShutdownInitializer
from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry

logger = logging.getLogger(__name__)

HookJob = tuple[str, Coroutine[object, object, object]]


@inject
class BackgroundHookRegistry:
    """Application-scoped owner of ``background`` hooks that outlive their request.

    Bounds how many run at once, keeps them referenced until done, runs the request's teardown
    (``RequestAsyncCloseRegistry``) once its hooks are finished, and drains them on shutdown.
    """

    def __init__(self, settings: BackgroundHookSettings) -> None:
        self._settings = settings
        self._hook_tasks: set[asyncio.Task[object]] = set()
        self._supervisors: set[asyncio.Task[None]] = set()

    def start(
        self, jobs: Sequence[HookJob], close_registry: RequestAsyncCloseRegistry
    ) -> list[asyncio.Task[object]]:
        """Start the jobs of one request and take over that request's teardown.

        Jobs beyond the concurrency limit are dropped with a warning. When none is accepted,
        the teardown stays with the request.
        """
        accepted = self._admit(jobs)
        if not accepted:
            return []

        release = close_registry.hand_off()
        tasks: list[asyncio.Task[object]] = []
        for name, coroutine in accepted:
            task = asyncio.create_task(coroutine, name=f"background-hook:{name}")
            self._hook_tasks.add(task)
            task.add_done_callback(self._hook_tasks.discard)
            tasks.append(task)

        supervisor = asyncio.create_task(self._supervise(tasks, release), name="background-hooks")
        self._supervisors.add(supervisor)
        supervisor.add_done_callback(self._supervisors.discard)
        return tasks

    def _admit(self, jobs: Sequence[HookJob]) -> list[HookJob]:
        """Keep the jobs that fit under the concurrency limit; close and log the rest."""
        free = max(self._settings.max_concurrent - len(self._hook_tasks), 0)
        accepted, dropped = list(jobs[:free]), list(jobs[free:])
        for name, coroutine in dropped:
            coroutine.close()
            logger.warning(
                "Background hook %r dropped: %d already running (limit %d)",
                name,
                len(self._hook_tasks),
                self._settings.max_concurrent,
            )
        return accepted

    @staticmethod
    async def _supervise(
        tasks: list[asyncio.Task[object]], release: Callable[[], Awaitable[None]]
    ) -> None:
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await release()

    async def shutdown(self) -> None:
        pending = {task for task in self._supervisors if not task.done()}
        if not pending:
            return
        grace = self._settings.shutdown_grace_seconds
        logger.info("Draining %d background hook group(s), up to %.0fs", len(pending), grace)
        _, unfinished = await asyncio.wait(pending, timeout=grace)
        if unfinished:
            logger.warning(
                "Cancelling %d background hook group(s) that did not finish in time",
                len(unfinished),
            )
            for task in unfinished:
                task.cancel()
            await asyncio.gather(*unfinished, return_exceptions=True)


@inject
class _BackgroundHookShutdown(ShutdownInitializer):
    """Drains background hooks when the application stops."""

    def __init__(self, registry: BackgroundHookRegistry) -> None:
        self._registry = registry

    async def initialize(self) -> None:
        await self._registry.shutdown()
