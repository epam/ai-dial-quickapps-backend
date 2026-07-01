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
