import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from injector import inject
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunTaskSettings(BaseSettings):
    """Operator-level bounds on delegated tasks.

    Tasks share the replica's event loop and memory, so without these one decision
    of the delegating agent can fan out into unbounded work of unbounded duration.
    """

    model_config = SettingsConfigDict()

    timeout_seconds: float = Field(
        default=600.0,
        description=(
            "Admin ceiling on how long one task may run. An app's "
            "`features.run_task.timeout_seconds` may shorten it, never extend it."
        ),
        alias="RUN_TASK_TIMEOUT_SECONDS",
        gt=0,
    )
    max_concurrent: int = Field(
        default=4,
        description=(
            "Maximum tasks running at once in this process, across all requests. "
            "Excess tasks wait for a slot, up to the task's time budget."
        ),
        alias="RUN_TASK_MAX_CONCURRENT",
        gt=0,
    )


@inject
class TaskSemaphore:
    """Caps concurrent tasks per process; excess tasks wait for a slot, for a bounded time.

    Singleton: it protects the replica, which every concurrent request draws on. The
    semaphore is built on first use because the DI graph is wired before a loop runs.
    """

    def __init__(self, settings: RunTaskSettings) -> None:
        self._limit = settings.max_concurrent
        self._semaphore: asyncio.Semaphore | None = None

    @asynccontextmanager
    async def hold(self, wait_seconds: float) -> AsyncIterator[None]:
        """Hold a slot; raises ``TaskQueueTimeout`` if none frees up in ``wait_seconds``."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._limit)
        try:
            async with asyncio.timeout(wait_seconds):
                await self._semaphore.acquire()
        except TimeoutError:
            raise TaskQueueTimeout() from None
        try:
            yield
        finally:
            self._semaphore.release()


class TaskQueueTimeout(Exception):
    """No task slot freed up within the wait limit."""
