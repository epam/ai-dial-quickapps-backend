"""Tests for RequestAsyncCloseRegistry: runs all closers, swallows errors, drains once."""

import pytest

from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry


@pytest.mark.asyncio
async def test_aclose_all_runs_every_registered_closer():
    registry = RequestAsyncCloseRegistry()
    calls: list[str] = []

    async def _first() -> None:
        calls.append("first")

    async def _second() -> None:
        calls.append("second")

    registry.register("first", _first)
    registry.register("second", _second)

    await registry.aclose_all()

    assert calls == ["first", "second"]


@pytest.mark.asyncio
async def test_aclose_all_swallows_errors_and_continues():
    registry = RequestAsyncCloseRegistry()
    calls: list[str] = []

    async def _boom() -> None:
        raise RuntimeError("teardown failed")

    async def _ok() -> None:
        calls.append("ok")

    registry.register("boom", _boom)
    registry.register("ok", _ok)

    # A failing closer must neither raise nor prevent the others from running.
    await registry.aclose_all()

    assert calls == ["ok"]


@pytest.mark.asyncio
async def test_aclose_all_drains_so_second_call_is_noop():
    registry = RequestAsyncCloseRegistry()
    calls: list[str] = []

    async def _closer() -> None:
        calls.append("x")

    registry.register("x", _closer)

    await registry.aclose_all()
    await registry.aclose_all()  # already drained — must not re-run

    assert calls == ["x"]


@pytest.mark.asyncio
async def test_aclose_all_with_no_closers_is_noop():
    registry = RequestAsyncCloseRegistry()
    await registry.aclose_all()


@pytest.mark.asyncio
async def test_aclose_all_does_nothing_after_hand_off():
    registry = RequestAsyncCloseRegistry()
    calls: list[str] = []

    async def _closer() -> None:
        calls.append("closed")

    registry.register("closer", _closer)
    registry.hand_off()

    await registry.aclose_all()

    assert calls == []


@pytest.mark.asyncio
async def test_hand_off_returns_the_callable_that_runs_the_closers_once():
    registry = RequestAsyncCloseRegistry()
    calls: list[str] = []

    async def _closer() -> None:
        calls.append("closed")

    registry.register("closer", _closer)
    release = registry.hand_off()

    await registry.aclose_all()
    assert calls == []
    await release()
    await release()

    assert calls == ["closed"]


@pytest.mark.asyncio
async def test_closers_run_when_the_request_finishes_last():
    registry = RequestAsyncCloseRegistry()
    calls: list[str] = []

    async def _closer() -> None:
        calls.append("closed")

    registry.register("closer", _closer)
    release = registry.hand_off()

    await release()
    assert calls == []
    await registry.aclose_all()

    assert calls == ["closed"]


@pytest.mark.asyncio
async def test_closers_wait_for_every_hand_off():
    registry = RequestAsyncCloseRegistry()
    calls: list[str] = []

    async def _closer() -> None:
        calls.append("closed")

    registry.register("closer", _closer)
    first, second = registry.hand_off(), registry.hand_off()

    await registry.aclose_all()
    await first()
    assert calls == []
    await second()

    assert calls == ["closed"]


@pytest.mark.asyncio
async def test_closers_registered_after_hand_off_are_run_by_the_new_owner():
    registry = RequestAsyncCloseRegistry()
    calls: list[str] = []

    async def _late() -> None:
        calls.append("late")

    release = registry.hand_off()
    registry.register("late", _late)
    await registry.aclose_all()
    await release()

    assert calls == ["late"]


@pytest.mark.asyncio
async def test_failing_closer_after_hand_off_does_not_stop_the_others():
    registry = RequestAsyncCloseRegistry()
    calls: list[str] = []

    async def _boom() -> None:
        raise RuntimeError("teardown failed")

    async def _ok() -> None:
        calls.append("ok")

    registry.register("boom", _boom)
    registry.register("ok", _ok)

    release = registry.hand_off()
    await registry.aclose_all()
    await release()

    assert calls == ["ok"]
