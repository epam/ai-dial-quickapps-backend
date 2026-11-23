import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

import pytest
from injector import Injector

from quickapp.agent_hooks._background_hook_settings import BackgroundHookSettings
from quickapp.agent_hooks._background_registry import BackgroundHookRegistry, BackgroundHookShutdown
from quickapp.agent_hooks.agent_hooks_module import AgentHooksModule
from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry


def _registry(max_concurrent: int = 50, grace: float = 30.0) -> BackgroundHookRegistry:
    return BackgroundHookRegistry(
        BackgroundHookSettings(max_concurrent=max_concurrent, shutdown_grace_seconds=grace)
    )


def _close_registry(calls: list[str]) -> RequestAsyncCloseRegistry:
    close_registry = RequestAsyncCloseRegistry()

    async def _close() -> None:
        calls.append("closed")

    close_registry.register("res", _close)
    return close_registry


async def _wait_for(event: asyncio.Event) -> str:
    await event.wait()
    return "done"


async def _boom() -> str:
    raise RuntimeError("boom")


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def _set_event() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


class TestStart:
    @pytest.mark.asyncio
    async def test_request_teardown_is_deferred_until_every_hook_finished(self) -> None:
        calls: list[str] = []
        close_registry = _close_registry(calls)
        gate = asyncio.Event()
        registry = _registry()

        tasks = registry.start([("a", _wait_for(gate))], close_registry)
        await close_registry.aclose_all()
        await _settle()
        assert calls == []

        gate.set()
        await asyncio.gather(*tasks)
        await registry.shutdown()
        assert calls == ["closed"]

    @pytest.mark.asyncio
    async def test_teardown_waits_for_all_hooks_of_the_request(self) -> None:
        calls: list[str] = []
        close_registry = _close_registry(calls)
        first, second = asyncio.Event(), asyncio.Event()
        registry = _registry()

        registry.start([("a", _wait_for(first)), ("b", _wait_for(second))], close_registry)
        await close_registry.aclose_all()
        first.set()
        await _settle()
        assert calls == []

        second.set()
        await registry.shutdown()
        assert calls == ["closed"]

    @pytest.mark.asyncio
    async def test_failing_hook_still_lets_teardown_run(self) -> None:
        calls: list[str] = []
        registry = _registry()

        close_registry = _close_registry(calls)
        registry.start([("a", _boom())], close_registry)
        await close_registry.aclose_all()
        await registry.shutdown()

        assert calls == ["closed"]

    @pytest.mark.asyncio
    async def test_teardown_waits_for_the_request_when_hooks_finish_first(self) -> None:
        calls: list[str] = []
        close_registry = _close_registry(calls)
        registry = _registry()

        tasks = registry.start([("a", _boom())], close_registry)
        await asyncio.gather(*tasks, return_exceptions=True)
        await registry.shutdown()
        assert calls == []  # the request still needs its resources

        await close_registry.aclose_all()
        assert calls == ["closed"]

    @pytest.mark.asyncio
    async def test_hooks_beyond_the_limit_are_dropped_with_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        gate = asyncio.Event()
        registry = _registry(max_concurrent=1)
        dropped: Coroutine[Any, Any, object] = _wait_for(gate)

        with caplog.at_level(logging.WARNING):
            tasks = registry.start(
                [("kept", _wait_for(gate)), ("extra", dropped)], _close_registry([])
            )

        assert len(tasks) == 1
        assert "'extra' dropped" in caplog.text
        assert dropped.cr_frame is None  # closed, never awaited
        gate.set()
        await registry.shutdown()

    @pytest.mark.asyncio
    async def test_limit_counts_hooks_still_running_from_earlier_requests(self) -> None:
        gate = asyncio.Event()
        registry = _registry(max_concurrent=1)
        registry.start([("first", _wait_for(gate))], _close_registry([]))

        tasks = registry.start([("second", _wait_for(gate))], _close_registry([]))

        assert tasks == []
        gate.set()
        await registry.shutdown()

    @pytest.mark.asyncio
    async def test_slot_is_free_again_once_a_hook_finished(self) -> None:
        registry = _registry(max_concurrent=1)
        first = registry.start([("first", _wait_for(_set_event()))], _close_registry([]))
        await asyncio.gather(*first)
        await _settle()

        second = registry.start([("second", _wait_for(_set_event()))], _close_registry([]))

        assert len(second) == 1
        await registry.shutdown()

    @pytest.mark.asyncio
    async def test_teardown_stays_with_the_request_when_nothing_was_given(self) -> None:
        calls: list[str] = []
        close_registry = _close_registry(calls)

        assert _registry().start([], close_registry) == []
        await close_registry.aclose_all()

        assert calls == ["closed"]

    @pytest.mark.asyncio
    async def test_teardown_stays_with_the_request_when_every_hook_was_dropped(self) -> None:
        calls: list[str] = []
        close_registry = _close_registry(calls)
        gate = asyncio.Event()
        registry = _registry(max_concurrent=1)
        registry.start([("kept", _wait_for(gate))], _close_registry([]))

        registry.start([("dropped", _wait_for(gate))], close_registry)
        await close_registry.aclose_all()

        assert calls == ["closed"]
        gate.set()
        await registry.shutdown()


class TestShutdown:
    @pytest.mark.asyncio
    async def test_returns_at_once_when_nothing_is_running(self) -> None:
        await _registry().shutdown()

    @pytest.mark.asyncio
    async def test_waits_for_running_hooks_within_the_grace_period(self) -> None:
        calls: list[str] = []
        gate = asyncio.Event()
        registry = _registry(grace=5.0)
        close_registry = _close_registry(calls)
        tasks = registry.start([("a", _wait_for(gate))], close_registry)
        await close_registry.aclose_all()

        asyncio.get_running_loop().call_later(0.05, gate.set)
        await registry.shutdown()

        assert tasks[0].result() == "done"
        assert calls == ["closed"]

    @pytest.mark.asyncio
    async def test_cancels_hooks_that_outlast_the_grace_period_and_still_tears_down(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls: list[str] = []
        registry = _registry(grace=0.05)
        close_registry = _close_registry(calls)
        tasks = registry.start([("stuck", _wait_for(asyncio.Event()))], close_registry)
        await close_registry.aclose_all()

        with caplog.at_level(logging.WARNING):
            await registry.shutdown()

        assert tasks[0].cancelled()
        assert calls == ["closed"]
        assert "Cancelling 1 background hook group(s)" in caplog.text

    @pytest.mark.asyncio
    async def test_shutdown_initializer_drains_the_registry(self) -> None:
        calls: list[str] = []
        registry = _registry(grace=0.05)
        close_registry = _close_registry(calls)
        registry.start([("stuck", _wait_for(asyncio.Event()))], close_registry)
        await close_registry.aclose_all()

        await BackgroundHookShutdown(registry).initialize()

        assert calls == ["closed"]


class TestWiring:
    def test_registry_is_one_shared_instance(self) -> None:
        injector = Injector([AgentHooksModule()])

        assert injector.get(BackgroundHookRegistry) is injector.get(BackgroundHookRegistry)
