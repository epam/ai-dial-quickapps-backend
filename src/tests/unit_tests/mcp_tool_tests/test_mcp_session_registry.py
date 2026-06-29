"""Tests for _MCPSessionRegistry: lazy open, reuse, concurrent dedup, failure handling, teardown."""

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry
from quickapp.mcp_tooling._mcp_session_registry import _MCPSessionRegistry


def _make_opener(
    session: object,
    *,
    fail_with: BaseException | None = None,
    counters: dict[str, int] | None = None,
) -> Callable[[], object]:
    """Build a zero-arg opener yielding the session, tracking open/close counts."""

    @asynccontextmanager
    async def _opener():
        if counters is not None:
            counters["open"] += 1
        if fail_with is not None:
            raise fail_with
        try:
            yield session
        finally:
            if counters is not None:
                counters["close"] += 1

    return _opener


@pytest.mark.asyncio
async def test_get_session_opens_once_and_reuses():
    registry = _MCPSessionRegistry(RequestAsyncCloseRegistry())
    session = MagicMock()
    counters = {"open": 0, "close": 0}
    opener = _make_opener(session, counters=counters)

    first = await registry.get_session("k", opener)
    second = await registry.get_session("k", opener)

    assert first is session
    assert second is session
    assert counters["open"] == 1  # opened exactly once, then reused

    await registry.aclose_all()
    assert counters["close"] == 1  # torn down exactly once


@pytest.mark.asyncio
async def test_concurrent_first_calls_share_one_owner():
    registry = _MCPSessionRegistry(RequestAsyncCloseRegistry())
    session = MagicMock()
    counters = {"open": 0, "close": 0}
    opener = _make_opener(session, counters=counters)

    results = await asyncio.gather(
        registry.get_session("k", opener),
        registry.get_session("k", opener),
        registry.get_session("k", opener),
    )

    assert all(r is session for r in results)
    assert counters["open"] == 1  # concurrent first-calls dedup to one owner

    await registry.aclose_all()


@pytest.mark.asyncio
async def test_distinct_keys_open_distinct_sessions():
    registry = _MCPSessionRegistry(RequestAsyncCloseRegistry())
    session_a, session_b = MagicMock(), MagicMock()

    got_a = await registry.get_session("a", _make_opener(session_a))
    got_b = await registry.get_session("b", _make_opener(session_b))

    assert got_a is session_a
    assert got_b is session_b

    await registry.aclose_all()


@pytest.mark.asyncio
async def test_failed_open_not_memoized_then_reopens():
    registry = _MCPSessionRegistry(RequestAsyncCloseRegistry())
    boom = RuntimeError("open failed")

    with pytest.raises(RuntimeError, match="open failed"):
        await registry.get_session("k", _make_opener(MagicMock(), fail_with=boom))

    # A retry (e.g. after interactive login) must re-open rather than see a cached failure.
    session = MagicMock()
    counters = {"open": 0, "close": 0}
    reopened = await registry.get_session("k", _make_opener(session, counters=counters))

    assert reopened is session
    assert counters["open"] == 1

    await registry.aclose_all()


@pytest.mark.asyncio
async def test_aclose_all_via_request_async_close_registry():
    """The registry self-registers, so closing the request-level registry tears down sessions."""
    close_registry = RequestAsyncCloseRegistry()
    registry = _MCPSessionRegistry(close_registry)
    counters = {"open": 0, "close": 0}

    await registry.get_session("k", _make_opener(MagicMock(), counters=counters))
    assert counters["close"] == 0

    await close_registry.aclose_all()
    assert counters["close"] == 1


@pytest.mark.asyncio
async def test_aclose_all_idempotent_when_no_sessions():
    registry = _MCPSessionRegistry(RequestAsyncCloseRegistry())
    # No sessions opened — teardown is a no-op and must not raise.
    await registry.aclose_all()
