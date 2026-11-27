import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine, Sequence

from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.agent_hooks._background_hook_settings import BackgroundHookSettings
from quickapp.common.base_finalizer import BaseFinalizer
from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry

logger = logging.getLogger(__name__)

HookJob = tuple[str, Coroutine[object, object, object]]


class StartResult(BaseModel):
    """Outcome of ``BackgroundHookRegistry.start``: the running tasks and the rejected hook names."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    tasks: list[asyncio.Task[object]]
    rejected: list[str]


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
    ) -> StartResult:
        """Start the jobs of one request and take over that request's teardown.

        Jobs beyond the concurrency limit are rejected (logged at ERROR, named in the result).
        Jobs that start above the warning threshold are logged with a warning. When none is
        accepted, the teardown stays with the request.
        """
        accepted, rejected = self._admit(jobs)
        if not accepted:
            return StartResult(tasks=[], rejected=rejected)

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
        return StartResult(tasks=tasks, rejected=rejected)

    def _admit(self, jobs: Sequence[HookJob]) -> tuple[list[HookJob], list[str]]:
        """Split the jobs into those that fit under the limit and the names of the rest."""
        running = len(self._hook_tasks)
        limit = self._settings.max_concurrent
        threshold = self._settings.warn_threshold
        accepted: list[HookJob] = []
        rejected: list[str] = []
        for name, coroutine in jobs:
            if running >= limit:
                coroutine.close()
                rejected.append(name)
                logger.error(
                    "Background hook %r rejected: %d already running (limit %d)",
                    name,
                    running,
                    limit,
                )
                continue
            running += 1
            accepted.append((name, coroutine))
            if running > threshold:
                logger.warning(
                    "Background hook pool is filling up: %d running after starting %r "
                    "(warning threshold %d, limit %d)",
                    running,
                    name,
                    threshold,
                    limit,
                )
        return accepted, rejected

    @staticmethod
    async def _supervise(
        tasks: list[asyncio.Task[object]], release: Callable[[], Awaitable[None]]
    ) -> None:
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await release()

    async def shutdown(self) -> None:
        """Wait up to the grace period for running hooks, then cancel what is left.

        Groups started while draining are picked up too: the snapshot is retaken until none is
        pending or the grace period is spent.
        """
        grace = self._settings.shutdown_grace_seconds
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace
        logged = False
        while pending := {task for task in self._supervisors if not task.done()}:
            if not logged:
                logger.info(
                    "Draining %d background hook group(s), up to %.0fs", len(pending), grace
                )
                logged = True
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.wait(pending, timeout=remaining)

        unfinished = {task for task in self._supervisors if not task.done()}
        if unfinished:
            logger.warning(
                "Cancelling %d background hook group(s) that did not finish in time",
                len(unfinished),
            )
            for task in unfinished:
                task.cancel()
            await asyncio.gather(*unfinished, return_exceptions=True)


@inject
class _BackgroundHookShutdown(BaseFinalizer):
    """Drains background hooks when the application stops."""

    def __init__(self, registry: BackgroundHookRegistry) -> None:
        self._registry = registry

    async def finalize(self) -> None:
        await self._registry.shutdown()
