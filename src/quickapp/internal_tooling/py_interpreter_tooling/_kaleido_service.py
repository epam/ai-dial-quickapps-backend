import asyncio
import json
import logging
from typing import Any

from kaleido import Kaleido

from quickapp.common.lifecycle_resource import LifecycleResource

logger = logging.getLogger(__name__)


class _KaleidoService(LifecycleResource):
    def __init__(self) -> None:
        self._kaleido: Kaleido | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        if self._kaleido is not None:
            logger.info("Stopping Kaleido service")
            try:
                await self._kaleido.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error stopping Kaleido service")
            finally:
                self._kaleido = None

    async def _ensure_started(self) -> Kaleido:
        if self._kaleido is None:
            async with self._lock:
                if self._kaleido is None:
                    logger.info("Starting Kaleido service (lazy init)")
                    kaleido = Kaleido(n=1, timeout=90)
                    await kaleido.__aenter__()
                    self._kaleido = kaleido
                    logger.info("Kaleido service started")
        return self._kaleido

    async def render_figure_as_png(self, figure_json: str | dict[str, Any]) -> bytes:
        kaleido = await self._ensure_started()
        fig_dict = json.loads(figure_json) if isinstance(figure_json, str) else figure_json
        data = await kaleido.calc_fig(fig_dict, opts={"format": "png"})
        if data is None:
            raise RuntimeError("Kaleido returned no data for the figure")
        return bytes(data)
