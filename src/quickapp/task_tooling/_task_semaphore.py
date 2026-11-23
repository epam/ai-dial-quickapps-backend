import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from injector import inject

from ._run_task_settings import RunTaskSettings


class TaskQueueTimeout(Exception):
    """No task slot freed up within the wait limit."""


@inject
class TaskSemaphore:
    """Caps concurrent tasks per process; excess tasks wait for a slot, for a bounded time.

    Singleton: it protects the replica, which every concurrent request draws on.
    """

    def __init__(self, settings: RunTaskSettings) -> None:
        self._semaphore = asyncio.Semaphore(settings.max_concurrent)

    @asynccontextmanager
    async def hold(self, wait_seconds: float) -> AsyncGenerator[None]:
        """Hold a slot; raises ``TaskQueueTimeout`` if none frees up in ``wait_seconds``."""
        try:
            async with asyncio.timeout(wait_seconds):
                await self._semaphore.acquire()
        except TimeoutError:
            raise TaskQueueTimeout() from None
        try:
            yield
        finally:
            self._semaphore.release()
