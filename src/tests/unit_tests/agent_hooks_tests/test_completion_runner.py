import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Status

from quickapp.agent_hooks._background_hook_settings import BackgroundHookSettings
from quickapp.agent_hooks._background_registry import BackgroundHookRegistry, StartResult
from quickapp.agent_hooks._completion_runner import _CompletionHookRunner
from quickapp.agent_hooks._context_factory import HookContextFactory
from quickapp.agent_hooks._dispatcher import HookDispatcher
from quickapp.common.hook_context.context import CompletionHookContext
from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry
from quickapp.config.hooks import HookEvent, ToolCallHookConfig


class _Harness:
    def __init__(self, hooks: list[ToolCallHookConfig] | None, hold: float = 3.0) -> None:
        self.factory = MagicMock(spec=HookContextFactory)
        self.dispatcher = MagicMock(spec=HookDispatcher)
        self.dispatcher.hooks_for.side_effect = lambda event: [
            h for h in hooks or [] if h.event == event
        ]
        self.dispatcher.run_all = AsyncMock(return_value=[])

        async def _noop() -> None:
            return None

        self.dispatcher.prepare_hook.side_effect = lambda hook, context: _noop()
        self.registry = MagicMock(spec=BackgroundHookRegistry)
        self.registry.start.return_value = StartResult(tasks=[], rejected=[])
        self.choice = MagicMock()
        self.close_registry = RequestAsyncCloseRegistry()
        self.runner = _CompletionHookRunner(
            self.factory,
            self.dispatcher,
            self.registry,
            self.close_registry,
            BackgroundHookSettings(response_hold_seconds=hold),
            self.choice,
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
            return StartResult(tasks=[], rejected=[])

        async def _run_all(hooks, context):
            order.append("run_all")
            return []

        h.registry.start.side_effect = _start
        h.dispatcher.run_all.side_effect = _run_all

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        assert order == ["start", "run_all"]

    @pytest.mark.asyncio
    async def test_response_waits_at_most_the_hold_period_for_background_hooks(self) -> None:
        h = _Harness([_completion("bg", "background")], hold=0.05)
        stuck = asyncio.create_task(asyncio.sleep(10))
        h.registry.start.return_value = StartResult(tasks=[stuck], rejected=[])
        started = asyncio.get_running_loop().time()

        try:
            await h.runner.run(iteration_count=1, total_tool_calls=0)
            assert asyncio.get_running_loop().time() - started < 1
            assert not stuck.done()
        finally:
            stuck.cancel()

    @pytest.mark.asyncio
    async def test_fast_background_hook_does_not_hold_the_response(self) -> None:
        h = _Harness([_completion("bg", "background")], hold=5.0)
        h.registry.start.return_value = StartResult(
            tasks=[asyncio.create_task(asyncio.sleep(0))], rejected=[]
        )
        started = asyncio.get_running_loop().time()

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        assert asyncio.get_running_loop().time() - started < 1

    @pytest.mark.asyncio
    async def test_hold_period_is_measured_from_the_start_not_after_blocking_hooks(self) -> None:
        h = _Harness([_completion("bg", "background"), _completion("inline")], hold=0.3)
        stuck = asyncio.create_task(asyncio.sleep(10))
        h.registry.start.return_value = StartResult(tasks=[stuck], rejected=[])

        async def _slow_blocking(hooks, context):
            await asyncio.sleep(0.6)
            return []

        h.dispatcher.run_all.side_effect = _slow_blocking
        started = asyncio.get_running_loop().time()

        try:
            await h.runner.run(iteration_count=1, total_tool_calls=0)
            # Waited for the blocking hook (0.6s) only; the 0.3s hold had already elapsed,
            # so nothing is added (it would be ~0.9s if measured after the blocking hooks).
            assert asyncio.get_running_loop().time() - started < 0.75
        finally:
            stuck.cancel()

    @pytest.mark.asyncio
    async def test_handlers_are_resolved_before_the_tasks_are_started(self) -> None:
        h = _Harness([_completion("bg", "background")])
        order: list[str] = []
        h.dispatcher.prepare_hook.side_effect = lambda hook, context: (
            order.append("prepare"),
            asyncio.sleep(0),
        )[1]

        def _start(jobs, close_registry):
            order.append("start")
            for _, coroutine in jobs:
                coroutine.close()
            return StartResult(tasks=[], rejected=[])

        h.registry.start.side_effect = _start

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        assert order == ["prepare", "start"]


class TestSplitByExecution:
    def test_splits_preserving_manifest_order(self) -> None:
        a, b, c = _completion("a"), _completion("b", "background"), _completion("c")

        background, blocking = _CompletionHookRunner._split_by_execution([a, b, c])

        assert background == [b]
        assert blocking == [a, c]


class TestRejectedHooks:
    @pytest.mark.asyncio
    async def test_rejected_hook_is_shown_as_a_failed_stage(self) -> None:
        h = _Harness([_completion("bg", "background")])
        h.registry.start.return_value = StartResult(tasks=[], rejected=["bg"])

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        h.choice.create_stage.assert_called_once_with("Hook bg")
        stage = h.choice.create_stage.return_value.__enter__.return_value
        stage.close.assert_called_once_with(Status.FAILED)

    @pytest.mark.asyncio
    async def test_stage_failure_does_not_fail_the_run_or_skip_blocking_hooks(self) -> None:
        h = _Harness([_completion("bg", "background"), _completion("inline")])
        h.registry.start.return_value = StartResult(tasks=[], rejected=["bg"])
        h.choice.create_stage.side_effect = RuntimeError("closed choice")

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        h.dispatcher.run_all.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_stage_when_nothing_was_rejected(self) -> None:
        h = _Harness([_completion("bg", "background")])

        await h.runner.run(iteration_count=1, total_tool_calls=0)

        h.choice.create_stage.assert_not_called()
