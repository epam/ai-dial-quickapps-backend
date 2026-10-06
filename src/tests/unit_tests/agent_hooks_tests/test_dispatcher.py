import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.agent_hooks._dispatcher import (
    _EVENT_DEFAULT_TIMEOUT,
    HookDispatcher,
    _resolve_timeout,
)
from quickapp.agent_hooks._handlers import HookHandler, HookHandlerRegistry
from quickapp.common.hook_context.context import HookResult, RequestStartHookContext
from quickapp.config.hooks import HookEvent, ToolCallHookConfig
from tests.unit_tests.common.common import make_provider

_CONTEXT = RequestStartHookContext(event="on_request_start", messages=[])


def _hook(name: str, event: str = "on_request_start", **overrides: Any) -> ToolCallHookConfig:
    return ToolCallHookConfig(event=event, tool_name="t", name=name, **overrides)


def _handler(result: HookResult | None = None, side_effect: Any = None) -> MagicMock:
    handler = MagicMock(spec=HookHandler)
    handler.run = AsyncMock(return_value=result, side_effect=side_effect)
    return handler


def _result(name: str) -> HookResult:
    return HookResult(hook_name=name, content=f"content-{name}")


def _dispatcher(hooks: list[ToolCallHookConfig], handlers: dict[str, MagicMock]) -> HookDispatcher:
    registry = MagicMock(spec=HookHandlerRegistry)
    registry.handler_for.side_effect = lambda hook: handlers[hook.name]
    return HookDispatcher(make_provider(SimpleNamespace(hooks=hooks)), registry)


async def _slow(context: Any) -> HookResult:
    await asyncio.sleep(5)
    return _result("slow")


class TestResolveTimeout:
    def test_hook_override_wins(self) -> None:
        assert _resolve_timeout(_hook("h", "on_completion", timeout_seconds=2.5)) == 2.5

    def test_completion_default_is_30_seconds(self) -> None:
        assert _resolve_timeout(_hook("h", "on_completion")) == 30.0

    def test_request_start_default_is_15_seconds(self) -> None:
        assert _resolve_timeout(_hook("h")) == 15.0


class TestRunHook:
    @pytest.mark.asyncio
    async def test_returns_handler_result(self) -> None:
        hook = _hook("a")
        dispatcher = _dispatcher([hook], {"a": _handler(_result("a"))})
        assert await dispatcher.run_hook(hook, _CONTEXT) == _result("a")

    @pytest.mark.asyncio
    async def test_slow_handler_is_cut_off_by_hook_timeout(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        hook = _hook("slow", timeout_seconds=0.01)
        dispatcher = _dispatcher([hook], {"slow": _handler(side_effect=_slow)})

        with caplog.at_level(logging.WARNING):
            assert await dispatcher.run_hook(hook, _CONTEXT) is None

        assert "slow" in caplog.text
        assert "timed out" in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event", [HookEvent.ON_COMPLETION, HookEvent.ON_REQUEST_START])
    async def test_event_default_timeout_is_applied(
        self, monkeypatch: pytest.MonkeyPatch, event: HookEvent
    ) -> None:
        monkeypatch.setitem(_EVENT_DEFAULT_TIMEOUT, event, 0.01)
        hook = _hook("slow", event.value)
        dispatcher = _dispatcher([hook], {"slow": _handler(side_effect=_slow)})
        assert await dispatcher.run_hook(hook, _CONTEXT) is None

    @pytest.mark.asyncio
    async def test_exception_is_logged_and_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        hook = _hook("bad")
        dispatcher = _dispatcher([hook], {"bad": _handler(side_effect=RuntimeError("boom"))})

        with caplog.at_level(logging.ERROR):
            assert await dispatcher.run_hook(hook, _CONTEXT) is None

        assert "bad" in caplog.text

    @pytest.mark.asyncio
    async def test_timeout_error_raised_inside_handler_is_treated_as_timeout(self) -> None:
        hook = _hook("t")
        dispatcher = _dispatcher([hook], {"t": _handler(side_effect=TimeoutError())})
        assert await dispatcher.run_hook(hook, _CONTEXT) is None

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self) -> None:
        hook = _hook("c")
        dispatcher = _dispatcher([hook], {"c": _handler(side_effect=asyncio.CancelledError())})
        with pytest.raises(asyncio.CancelledError):
            await dispatcher.run_hook(hook, _CONTEXT)


class TestDispatch:
    @pytest.mark.asyncio
    async def test_runs_only_hooks_of_the_event_in_manifest_order(self) -> None:
        hooks = [
            _hook("first"),
            _hook("other-event", "on_completion"),
            _hook("second"),
        ]
        handlers = {
            "first": _handler(_result("first")),
            "other-event": _handler(_result("other-event")),
            "second": _handler(_result("second")),
        }
        dispatcher = _dispatcher(hooks, handlers)

        results = await dispatcher.dispatch(HookEvent.ON_REQUEST_START, _CONTEXT)

        assert [r.hook_name for r in results] == ["first", "second"]
        handlers["other-event"].run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hooks_run_sequentially(self) -> None:
        order: list[str] = []

        def _recording(name: str) -> MagicMock:
            async def _run(context: Any) -> HookResult:
                order.append(f"start-{name}")
                await asyncio.sleep(0)
                order.append(f"end-{name}")
                return _result(name)

            return _handler(side_effect=_run)

        dispatcher = _dispatcher(
            [_hook("a"), _hook("b")], {"a": _recording("a"), "b": _recording("b")}
        )
        await dispatcher.dispatch(HookEvent.ON_REQUEST_START, _CONTEXT)

        assert order == ["start-a", "end-a", "start-b", "end-b"]

    @pytest.mark.asyncio
    async def test_drops_none_results_and_failed_hooks(self) -> None:
        hooks = [_hook("skipped"), _hook("failed"), _hook("ok")]
        handlers = {
            "skipped": _handler(None),
            "failed": _handler(side_effect=RuntimeError("boom")),
            "ok": _handler(_result("ok")),
        }
        results = await _dispatcher(hooks, handlers).dispatch(HookEvent.ON_REQUEST_START, _CONTEXT)
        assert [r.hook_name for r in results] == ["ok"]

    @pytest.mark.asyncio
    async def test_no_hooks_returns_empty_list(self) -> None:
        dispatcher = HookDispatcher(
            make_provider(SimpleNamespace(hooks=None)), MagicMock(spec=HookHandlerRegistry)
        )
        assert await dispatcher.dispatch(HookEvent.ON_REQUEST_START, _CONTEXT) == []
