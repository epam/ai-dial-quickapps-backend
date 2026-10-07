from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.agent_hooks._completion_runner import _CompletionHookRunner
from quickapp.agent_hooks._context_factory import HookContextFactory
from quickapp.agent_hooks._dispatcher import HookDispatcher
from quickapp.common.hook_context.context import CompletionHookContext
from quickapp.config.hooks import HookEvent, ToolCallHookConfig
from tests.unit_tests.common.common import make_provider


def _make_runner(
    hooks: list[ToolCallHookConfig] | None,
) -> tuple[_CompletionHookRunner, MagicMock, MagicMock]:
    factory = MagicMock(spec=HookContextFactory)
    dispatcher = MagicMock(spec=HookDispatcher)
    dispatcher.dispatch = AsyncMock(return_value=[])
    runner = _CompletionHookRunner(make_provider(SimpleNamespace(hooks=hooks)), factory, dispatcher)
    return runner, factory, dispatcher


def _hook(event: HookEvent) -> ToolCallHookConfig:
    return ToolCallHookConfig(event=event, tool_name="my_tool")


class TestCompletionHookRunner:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("hooks", [None, []])
    async def test_does_nothing_when_no_hooks_configured(self, hooks) -> None:
        runner, factory, dispatcher = _make_runner(hooks)

        await runner.run(iteration_count=1, total_tool_calls=0)

        factory.completion.assert_not_called()
        dispatcher.dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_nothing_when_only_request_start_hooks_configured(self) -> None:
        runner, factory, dispatcher = _make_runner([_hook(HookEvent.ON_REQUEST_START)])

        await runner.run(iteration_count=1, total_tool_calls=0)

        factory.completion.assert_not_called()
        dispatcher.dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dispatches_completion_event_with_built_context(self) -> None:
        runner, factory, dispatcher = _make_runner(
            [_hook(HookEvent.ON_REQUEST_START), _hook(HookEvent.ON_COMPLETION)]
        )
        context = CompletionHookContext(
            event="on_completion", messages=[], iteration_count=3, total_tool_calls=5
        )
        factory.completion.return_value = context

        await runner.run(iteration_count=3, total_tool_calls=5)

        factory.completion.assert_called_once_with(iteration_count=3, total_tool_calls=5)
        dispatcher.dispatch.assert_awaited_once_with(HookEvent.ON_COMPLETION, context)
