import asyncio

import pytest
from injector import Injector, Module, multiprovider

from quickapp.common.base_finalizer import BaseFinalizer, invoke_finalizers


class _Recording(BaseFinalizer):
    def __init__(
        self, name: str, calls: list[str], order: int = 0, error: BaseException | None = None
    ):
        self._name, self._calls, self._error = name, calls, error
        self.order = order  # type: ignore[misc]

    async def finalize(self) -> None:
        self._calls.append(self._name)
        if self._error:
            raise self._error


def _injector(*finalizers: BaseFinalizer) -> Injector:
    class _M(Module):
        @multiprovider
        def _provide(self) -> list[BaseFinalizer]:
            return list(finalizers)

    return Injector([_M()])


@pytest.mark.asyncio
async def test_no_binding_is_a_noop() -> None:
    await invoke_finalizers(Injector([]))


@pytest.mark.asyncio
async def test_runs_in_order() -> None:
    calls: list[str] = []
    await invoke_finalizers(_injector(_Recording("late", calls, 5), _Recording("early", calls, -1)))

    assert calls == ["early", "late"]


@pytest.mark.asyncio
async def test_failing_finalizer_does_not_skip_the_rest(caplog) -> None:
    calls: list[str] = []
    await invoke_finalizers(
        _injector(_Recording("bad", calls, error=RuntimeError("x")), _Recording("good", calls))
    )

    assert calls == ["bad", "good"]
    assert "_Recording" in caplog.text


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed() -> None:
    calls: list[str] = []
    with pytest.raises(asyncio.CancelledError):
        await invoke_finalizers(
            _injector(
                _Recording("c", calls, error=asyncio.CancelledError()), _Recording("n", calls)
            )
        )

    assert calls == ["c"]
