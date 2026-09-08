import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from injector import inject
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SubagentSettings(BaseSettings):
    """Operator-level bounds on subagent spawning.

    Spokes share the coordinator's process and event loop, so both limits protect a
    single replica: without them one coordinator decision can fan out into unbounded
    concurrent work with no upper bound on how long any of it runs.
    """

    model_config = SettingsConfigDict()

    timeout_seconds: float = Field(
        default=600.0,
        description=(
            "Admin ceiling on how long one spawn may run. A subagent's own "
            "`timeout_seconds` may shorten this but never extend it."
        ),
        alias="SUBAGENT_TIMEOUT_SECONDS",
        gt=0,
    )
    max_concurrent_spawns: int = Field(
        default=4,
        description=(
            "Maximum spawns running at once in this process, across all requests. "
            "Excess spawns queue rather than fail."
        ),
        alias="SUBAGENT_MAX_CONCURRENT_SPAWNS",
        gt=0,
    )


@inject
class SpawnSemaphore:
    """Caps concurrent spawns per process.

    Singleton, not request-scoped: the resource being protected is the replica's event
    loop and memory, which every concurrent user request draws on. The semaphore is
    built on first acquire because the DI graph is wired before there is a running loop.

    Excess spawns queue rather than fail — an LLM that fans out to twelve scouts should
    get twelve results slowly, not eight results and four errors. The per-spawn timeout
    bounds the wait, so a queued spawn cannot block forever.
    """

    def __init__(self, settings: SubagentSettings) -> None:
        self._limit = settings.max_concurrent_spawns
        self._semaphore: asyncio.Semaphore | None = None

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._limit)
        async with self._semaphore:
            yield
