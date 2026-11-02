import asyncio
import logging
from collections.abc import Callable, Coroutine
from contextlib import AbstractAsyncContextManager
from typing import TypeVar

from injector import inject
from mcp import ClientSession

from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# A zero-arg factory returning an async context manager that yields the live session.
SessionOpener = Callable[[], AbstractAsyncContextManager[ClientSession]]


def _retrieve_task_outcome(task: asyncio.Task) -> None:
    """Mark a task's exception as retrieved so a cancelled in-flight call does not warn."""
    if task.cancelled():
        return
    task.exception()


def _task_cancelled(task: asyncio.Task) -> bool:
    if task.cancelled():
        return True
    return isinstance(task.exception(), asyncio.CancelledError)


class _SessionHandle:
    """Bookkeeping for one toolset's live session and its owner task."""

    def __init__(self) -> None:
        self.ready: asyncio.Event = asyncio.Event()
        self.shutdown: asyncio.Event = asyncio.Event()
        self.session: ClientSession | None = None
        self.error: BaseException | None = None
        self.task: asyncio.Task | None = None


@inject
class _MCPSessionManager:
    """Owns one live, initialized MCP ``ClientSession`` per toolset for the whole request.

    Each session is opened inside a dedicated *owner task* that enters the
    transport/session async context, signals readiness, parks until a shutdown
    event, then exits the context itself. anyio requires a cancel scope to be
    exited in the task that entered it; tool calls run in concurrent sibling
    tasks, so the owner task is what keeps enter/exit co-located. Borrowers share
    the live session and may issue concurrent ``call_tool`` requests — the SDK
    multiplexes them by request id.

    Request-scoped: one manager instance per request. It self-registers its
    teardown with :class:`RequestAsyncCloseRegistry`, which the orchestrator
    flushes in its ``_persisting_state()`` ``finally`` block.
    """

    def __init__(self, async_close_registry: RequestAsyncCloseRegistry) -> None:
        self.__handles: dict[str, _SessionHandle] = {}
        self.__locks: dict[str, asyncio.Lock] = {}
        async_close_registry.register("mcp_sessions", self.aclose_all)

    async def get_session(self, key: str, opener: SessionOpener) -> ClientSession:
        """Return the live session for ``key``, opening it (once) on first use.

        Concurrent first-calls for the same key serialize on a per-key lock so a
        single owner task is spawned and its session shared. A failed open is not
        memoized — the handle is dropped so a later retry (e.g. after interactive
        login) re-opens.
        """
        # dict.setdefault is atomic on the event loop (no await), so concurrent
        # first-calls for the same key resolve to the same lock without a guard.
        lock = self.__locks.setdefault(key, asyncio.Lock())
        async with lock:
            handle = self.__handles.get(key)
            if handle is not None and handle.session is not None:
                return handle.session

            handle = _SessionHandle()
            self.__handles[key] = handle
            handle.task = asyncio.create_task(
                self.__run_owner(key, opener, handle), name=f"mcp-session-owner:{key}"
            )
            await handle.ready.wait()

            if handle.error is not None:
                # Do not memoize failures: drop the handle so a retry re-opens.
                self.__handles.pop(key, None)
                raise handle.error
            assert handle.session is not None
            return handle.session

    async def __run_owner(self, key: str, opener: SessionOpener, handle: _SessionHandle) -> None:
        try:
            async with opener() as session:
                handle.session = session
                handle.ready.set()
                await handle.shutdown.wait()
        except BaseException as exc:  # capture transport/init failures (incl. ExceptionGroup)
            handle.error = exc
            handle.session = None
            handle.ready.set()
            if isinstance(exc, asyncio.CancelledError):
                raise
            logger.debug("MCP session owner for '%s' ended with error: %s", key, type(exc).__name__)

    async def await_while_session_alive(self, key: str, call: Coroutine[object, object, _T]) -> _T:
        """Await ``call`` until it finishes or the session owner for ``key`` dies.

        The MCP streamable-HTTP client runs each POST in a background task and, on
        any status other than 202/404 (including 403), calls ``raise_for_status()``
        there. That exception kills the owner task and is never delivered to the
        in-flight ``call_tool`` / ``read_resource``, which would otherwise block
        until the tool read timeout — the chat turn then produces no reply.
        """
        handle = self.__handles.get(key)
        call_task = asyncio.create_task(call)
        call_task.add_done_callback(_retrieve_task_outcome)
        try:
            owner = handle.task if handle is not None else None
            if owner is None:
                return await call_task

            _done, _pending = await asyncio.wait(
                {call_task, owner}, return_when=asyncio.FIRST_COMPLETED
            )
            if call_task.done() and not _task_cancelled(call_task):
                return call_task.result()

            if not call_task.done():
                call_task.cancel()
                await asyncio.gather(call_task, return_exceptions=True)
            if handle is not None and handle.error is not None:
                raise handle.error
            raise RuntimeError("MCP session closed while a request was in flight")
        except asyncio.CancelledError:
            if not call_task.done():
                call_task.cancel()
            raise

    async def aclose_all(self) -> None:
        """Signal every owner task to exit its session context, then await them concurrently."""
        handles = list(self.__handles.values())
        self.__handles.clear()
        for handle in handles:
            handle.shutdown.set()
        tasks = [handle.task for handle in handles if handle.task is not None]
        if not tasks:
            return
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                logger.error("Failed while closing MCP session owner task", exc_info=result)
