import logging

from injector import ProviderOf, inject

from quickapp.agent_hooks._context_factory import HookContextFactory
from quickapp.agent_hooks._dispatcher import HookDispatcher
from quickapp.common.abstract.completion_hook_runner import CompletionHookRunner
from quickapp.config.application import ApplicationConfig
from quickapp.config.hooks import HookEvent

logger = logging.getLogger(__name__)


class _CompletionHookRunner(CompletionHookRunner):
    """Dispatches ``on_completion`` hooks once the orchestrator has finished a turn."""

    @inject
    def __init__(
        self,
        app_config_provider: ProviderOf[ApplicationConfig],
        context_factory: HookContextFactory,
        dispatcher: HookDispatcher,
    ) -> None:
        self._app_config_provider = app_config_provider
        self._context_factory = context_factory
        self._dispatcher = dispatcher

    async def run(self, *, iteration_count: int, total_tool_calls: int) -> None:
        if not self._has_completion_hooks():
            return
        context = self._context_factory.completion(
            iteration_count=iteration_count, total_tool_calls=total_tool_calls
        )
        await self._dispatcher.dispatch(HookEvent.ON_COMPLETION, context)

    def _has_completion_hooks(self) -> bool:
        hooks = self._app_config_provider.get().hooks or []
        return any(hook.event == HookEvent.ON_COMPLETION for hook in hooks)
