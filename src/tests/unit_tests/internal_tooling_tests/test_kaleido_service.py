import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quickapp.internal_tooling.py_interpreter_tooling._kaleido_service import _KaleidoService


@pytest.fixture
def service():
    return _KaleidoService()


@pytest.mark.asyncio
async def test_stop_when_not_started(service):
    await service.stop()
    assert service._kaleido is None


@pytest.mark.asyncio
async def test_lazy_start_on_first_render(service):
    mock_kaleido = MagicMock()
    mock_kaleido.__aenter__ = AsyncMock(return_value=mock_kaleido)
    mock_kaleido.__aexit__ = AsyncMock(return_value=None)
    mock_kaleido.calc_fig = AsyncMock(return_value=b"\x89PNG")

    with patch(
        "quickapp.internal_tooling.py_interpreter_tooling._kaleido_service.Kaleido",
        return_value=mock_kaleido,
    ) as mock_cls:
        result = await service.render_figure_as_png({"data": [{"y": [1, 2]}]})

        mock_cls.assert_called_once_with(n=1, timeout=90)
        mock_kaleido.__aenter__.assert_awaited_once()
        mock_kaleido.calc_fig.assert_awaited_once()
        assert result == b"\x89PNG"


@pytest.mark.asyncio
async def test_stop_after_lazy_start(service):
    mock_kaleido = MagicMock()
    mock_kaleido.__aenter__ = AsyncMock(return_value=mock_kaleido)
    mock_kaleido.__aexit__ = AsyncMock(return_value=None)
    mock_kaleido.calc_fig = AsyncMock(return_value=b"\x89PNG")

    with patch(
        "quickapp.internal_tooling.py_interpreter_tooling._kaleido_service.Kaleido",
        return_value=mock_kaleido,
    ):
        await service.render_figure_as_png({"data": [{"y": [1]}]})
        assert service._kaleido is not None

        await service.stop()
        mock_kaleido.__aexit__.assert_awaited_once()
        assert service._kaleido is None


@pytest.mark.asyncio
async def test_concurrent_lazy_start_creates_single_instance(service):
    mock_kaleido = MagicMock()
    mock_kaleido.__aenter__ = AsyncMock(return_value=mock_kaleido)
    mock_kaleido.__aexit__ = AsyncMock(return_value=None)
    mock_kaleido.calc_fig = AsyncMock(return_value=b"\x89PNG")

    with patch(
        "quickapp.internal_tooling.py_interpreter_tooling._kaleido_service.Kaleido",
        return_value=mock_kaleido,
    ) as mock_cls:
        results = await asyncio.gather(
            service.render_figure_as_png({"data": [{"y": [1]}]}),
            service.render_figure_as_png({"data": [{"y": [2]}]}),
            service.render_figure_as_png({"data": [{"y": [3]}]}),
        )

        mock_cls.assert_called_once()
        mock_kaleido.__aenter__.assert_awaited_once()
        assert all(r == b"\x89PNG" for r in results)


@pytest.mark.asyncio
async def test_render_with_json_string(service):
    mock_kaleido = MagicMock()
    mock_kaleido.__aenter__ = AsyncMock(return_value=mock_kaleido)
    mock_kaleido.__aexit__ = AsyncMock(return_value=None)
    mock_kaleido.calc_fig = AsyncMock(return_value=b"\x89PNG")

    with patch(
        "quickapp.internal_tooling.py_interpreter_tooling._kaleido_service.Kaleido",
        return_value=mock_kaleido,
    ):
        result = await service.render_figure_as_png('{"data": [{"y": [1, 2]}]}')

        call_args = mock_kaleido.calc_fig.call_args
        assert call_args[0][0] == {"data": [{"y": [1, 2]}]}
        assert result == b"\x89PNG"


@pytest.mark.asyncio
async def test_render_raises_on_none_result(service):
    mock_kaleido = MagicMock()
    mock_kaleido.__aenter__ = AsyncMock(return_value=mock_kaleido)
    mock_kaleido.__aexit__ = AsyncMock(return_value=None)
    mock_kaleido.calc_fig = AsyncMock(return_value=None)

    with patch(
        "quickapp.internal_tooling.py_interpreter_tooling._kaleido_service.Kaleido",
        return_value=mock_kaleido,
    ):
        with pytest.raises(RuntimeError, match="Kaleido returned no data"):
            await service.render_figure_as_png({"data": []})
