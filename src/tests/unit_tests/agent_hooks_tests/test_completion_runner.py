import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.agent_hooks import _completion_runner as runner_module
from quickapp.agent_hooks._background_registry import BackgroundHookRegistry
from quickapp.agent_hooks._completion_runner import _CompletionHookRunner
from quickapp.agent_hooks._context_factory import HookContextFactory
from quickapp.agent_hooks._dispatcher import HookDispatcher
from quickapp.common.hook_context.context import CompletionHookContext
from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry
from quickapp.config.hooks import HookEvent, ToolCallHookConfig


class _Harness:
    def __init__(self, hooks: list[ToolCallHookConfig] | None) -> None:
        self.factory = MagicMock(spec=HookContextFactory)
        self.dispatcher = MagicMock(spec=HookDispatcher)
        self.dispatcher.hooks_for.side_effect = lambda event: [
            h for h in hooks or [] if h.event == event
        ]
        self.dispatcher.run_all = AsyncMock(return_value=[])
        self.dispatcher.run_hook = AsyncMock(return_value=None)
        self.registry = MagicMock(spec=BackgroundHookRegistry)
        self.registry.start.return_value = []
        self.close_registry = RequestAsyncCloseRegistry()
        self.runner = _CompletionHookRunner(
            self.factory, self.dispatcher, self.registry, self.close_registry
        )


def _request_start() -> ToolCallHookConfig:
    return ToolCallHookConfig(event=HookEvent.ON_REQUEST_START, tool_name="my_tool")


def _completion(name: str, execution: str | None = None) -> ToolCallHookConfig:
    extra = {"execution": execution} if execution else {}
    return ToolCallHookConfig.model_validate(
        {"event": "on_completion", "tool_name": "my_tool", "name": name, **extra}
    )


class TestCompletionHookRunner:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("hooks", [None, []])
    async def test_does_nothing_when_no_hooks_configured(self, hooks) -> None:
        h = _Harness(hooks)

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        h.factory.completion.assert_not_called()
        h.dispatcher.run_all.assert_not_awaited()
        h.registry.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_nothing_when_only_request_start_hooks_configured(self) -> None:
        h = _Harness([_request_start()])

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        h.factory.completion.assert_not_called()
        h.dispatcher.run_all.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_runs_blocking_hooks_with_the_built_context(self) -> None:
        blocking = _completion("b")
        h = _Harness([_request_start(), blocking])
        context = CompletionHookContext(
            event="on_completion", messages=[], iteration_count=3, total_tool_calls=5
        )
        h.factory.completion.return_value = context

        await h.runner.run(iteration_count=3, total_tool_calls=5)

        h.factory.completion.assert_called_once_with(iteration_count=3, total_tool_calls=5)
        h.dispatcher.run_all.assert_awaited_once_with([blocking], context)

    @pytest.mark.asyncio
    async def test_background_hooks_are_handed_to_the_registry(self) -> None:
        background = _completion("bg", "background")
        blocking = _completion("inline")
        h = _Harness([background, blocking])

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        jobs, close_registry = h.registry.start.call_args.args
        assert [name for name, _ in jobs] == ["bg"]
        assert close_registry is h.close_registry
        for _, coroutine in jobs:
            coroutine.close()
        assert h.dispatcher.run_all.await_args.args[0] == [blocking]

    @pytest.mark.asyncio
    async def test_background_hooks_start_before_blocking_ones_run(self) -> None:
        h = _Harness([_completion("bg", "background"), _completion("inline")])
        order: list[str] = []

        def _start(jobs, close_registry):
            order.append("start")
            for _, coroutine in jobs:
                coroutine.close()
            return []

        async def _run_all(hooks, context):
            order.append("run_all")
            return []

        h.registry.start.side_effect = _start
        h.dispatcher.run_all.side_effect = _run_all

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        assert order == ["start", "run_all"]

    @pytest.mark.asyncio
    async def test_response_waits_at_most_the_grace_period_for_background_hooks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner_module, "_BACKGROUND_HOOK_GRACE_SECONDS", 0.05)
        h = _Harness([_completion("bg", "background")])
        stuck = asyncio.create_task(asyncio.sleep(10))
        h.registry.start.return_value = [stuck]
        started = asyncio.get_running_loop().time()

        try:
            await h.runner.run(iteration_count=1, total_tool_calls=0)
            assert asyncio.get_running_loop().time() - started < 1
            assert not stuck.done()
        finally:
            stuck.cancel()

    @pytest.mark.asyncio
    async def test_fast_background_hook_does_not_hold_the_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner_module, "_BACKGROUND_HOOK_GRACE_SECONDS", 5.0)
        h = _Harness([_completion("bg", "background")])
        h.registry.start.return_value = [asyncio.create_task(asyncio.sleep(0))]
        started = asyncio.get_running_loop().time()

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        assert asyncio.get_running_loop().time() - started < 1

    @pytest.mark.asyncio
    async def test_grace_period_is_measured_from_the_start_not_after_blocking_hooks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner_module, "_BACKGROUND_HOOK_GRACE_SECONDS", 0.1)
        h = _Harness([_completion("bg", "background"), _completion("inline")])
        stuck = asyncio.create_task(asyncio.sleep(10))
        h.registry.start.return_value = [stuck]

        async def _slow_blocking(hooks, context):
            await asyncio.sleep(0.2)
            return []

        h.dispatcher.run_all.side_effect = _slow_blocking
        started = asyncio.get_running_loop().time()

        try:
            await h.runner.run(iteration_count=1, total_tool_calls=0)
            assert asyncio.get_running_loop().time() - started < 0.3
        finally:
            stuck.cancel()
