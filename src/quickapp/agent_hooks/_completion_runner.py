import asyncio
import logging

from injector import inject

from quickapp.agent_hooks._background_hook_settings import BackgroundHookSettings
from quickapp.agent_hooks._background_registry import BackgroundHookRegistry
from quickapp.agent_hooks._context_factory import HookContextFactory
from quickapp.agent_hooks._dispatcher import HookDispatcher
from quickapp.agent_hooks._handlers import hook_display_name
from quickapp.common.abstract.completion_hook_runner import CompletionHookRunner
from quickapp.common.hook_context.context import HookContext
from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry
from quickapp.config.hooks import HookConfig, HookEvent, HookExecution

logger = logging.getLogger(__name__)


class _CompletionHookRunner(CompletionHookRunner):
    """Dispatches ``on_completion`` hooks once the orchestrator has finished a turn.

    ``blocking`` hooks run in manifest order and are awaited. ``background`` hooks are handed to
    the ``BackgroundHookRegistry`` first, so they overlap with the blocking ones.
    """

    @inject
    def __init__(
        self,
        context_factory: HookContextFactory,
        dispatcher: HookDispatcher,
        background_registry: BackgroundHookRegistry,
        close_registry: RequestAsyncCloseRegistry,
        settings: BackgroundHookSettings,
    ) -> None:
        self._settings = settings
        self._context_factory = context_factory
        self._dispatcher = dispatcher
        self._background_registry = background_registry
        self._close_registry = close_registry

    async def run(self, *, iteration_count: int, total_tool_calls: int) -> None:
        hooks = self._dispatcher.hooks_for(HookEvent.ON_COMPLETION)
        if not hooks:
            return
        context = self._context_factory.completion(
            iteration_count=iteration_count, total_tool_calls=total_tool_calls
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.response_hold_seconds

        background = [h for h in hooks if h.execution is HookExecution.BACKGROUND]
        started = self._start_background(background, context)
        await self._dispatcher.run_all(
            [h for h in hooks if h.execution is HookExecution.BLOCKING], context
        )
        if started:
            await asyncio.wait(started, timeout=max(deadline - loop.time(), 0))

    def _start_background(
        self, hooks: list[HookConfig], context: HookContext
    ) -> list[asyncio.Task[object]]:
        jobs = [
            (hook_display_name(hook), self._dispatcher.run_hook(hook, context)) for hook in hooks
        ]
        return self._background_registry.start(jobs, self._close_registry)
