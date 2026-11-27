import asyncio
import logging

from aidial_sdk.chat_completion import Choice, Status
from injector import inject

from quickapp.agent_hooks._background_hook_settings import BackgroundHookSettings
from quickapp.agent_hooks._background_registry import BackgroundHookRegistry, StartResult
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
        choice: Choice,
    ) -> None:
        self._choice = choice
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
        background, blocking = self._split_by_execution(hooks)
        deadline = self._hold_deadline()

        started = self._start_background(background, context)
        self._report_rejected(started.rejected)
        await self._dispatcher.run_all(blocking, context)
        await self._hold_for(started.tasks, deadline)

    @staticmethod
    def _split_by_execution(hooks: list[HookConfig]) -> tuple[list[HookConfig], list[HookConfig]]:
        background = [h for h in hooks if h.execution is HookExecution.BACKGROUND]
        blocking = [h for h in hooks if h.execution is not HookExecution.BACKGROUND]
        return background, blocking

    def _hold_deadline(self) -> float:
        return asyncio.get_running_loop().time() + self._settings.response_hold_seconds

    @staticmethod
    async def _hold_for(started: list[asyncio.Task[object]], deadline: float) -> None:
        """Keep the response open until the background hooks finish or the deadline passes.

        The tasks are not cancelled when the wait times out: they keep running after the response.
        """
        if not started:
            return
        remaining = max(deadline - asyncio.get_running_loop().time(), 0)
        await asyncio.wait(started, timeout=remaining)

    def _start_background(self, hooks: list[HookConfig], context: HookContext) -> StartResult:
        # prepare_hook resolves each handler here, inside the request, so the tasks need not.
        jobs = [
            (hook_display_name(hook), self._dispatcher.prepare_hook(hook, context))
            for hook in hooks
        ]
        return self._background_registry.start(jobs, self._close_registry)

    def _report_rejected(self, names: list[str]) -> None:
        """Show each hook the pool refused as a failed stage, so the user knows it did not run."""
        for name in names:
            try:
                with self._choice.create_stage(f"Hook {name}") as stage:
                    stage.append_content(
                        "The background hook was not started: too many background hooks are "
                        "already running. Its work was skipped."
                    )
                    stage.close(Status.FAILED)
            except Exception:
                logger.exception("Could not report the rejected background hook %r", name)
