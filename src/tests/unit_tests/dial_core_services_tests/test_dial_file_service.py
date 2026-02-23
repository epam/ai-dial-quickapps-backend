from contextlib import contextmanager
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from quickapp.common.dial_settings import DialSettings
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services.dial_file_service import DialFileService


def _make_service(state_holder: StateHolder | None = None) -> DialFileService:
    """Create a DialFileService with test settings."""
    dial_settings = DialSettings(url="https://dial-core", api_version="2025-01-01-preview")
    api_key = SecretStr("test-api-key")
    holder = state_holder or StateHolder()
    perf_timer = PerformanceTimer()
    return DialFileService(dial_settings, api_key, holder, perf_timer)


@contextmanager
def _mock_dial_core_client(**client_attrs: object) -> Generator[AsyncMock, None, None]:
    """Patch DialCoreClient and yield the mock client with the given attributes."""
    mock_client = AsyncMock(**client_attrs)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_client
    mock_ctx.__aexit__.return_value = None

    with patch(
        "quickapp.dial_core_services.dial_file_service.DialCoreClient",
        return_value=mock_ctx,
    ):
        yield mock_client


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_cache_miss_downloads_and_stores(self):
        svc = _make_service()
        file_bytes = b"file content"

        with _mock_dial_core_client(
            get_metadata=AsyncMock(return_value={"contentLength": 100}),
            get_file=AsyncMock(return_value=file_bytes),
        ) as mock_client:
            result = await svc.download_file("files/test.txt")

        assert result == file_bytes
        mock_client.get_file.assert_awaited_once_with("files/test.txt")

    @pytest.mark.asyncio
    async def test_cache_hit_returns_from_state(self):
        holder = StateHolder()
        holder.store_file_data("files/cached.txt", b"cached content")
        svc = _make_service(state_holder=holder)

        with patch(
            "quickapp.dial_core_services.dial_file_service.DialCoreClient",
        ) as mock_dc:
            result = await svc.download_file("files/cached.txt")

        assert result == b"cached content"
        mock_dc.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_exceeds_size_limit_raises_error(self):
        svc = _make_service()

        with _mock_dial_core_client(
            get_metadata=AsyncMock(return_value={"contentLength": 11 * 1024 * 1024}),
        ):
            with pytest.raises(ValueError, match="exceeds the limit"):
                await svc.download_file("files/huge.bin")


class TestGrantPermissions:
    @pytest.mark.asyncio
    async def test_grant_permissions_calls_client(self):
        svc = _make_service()

        with _mock_dial_core_client() as mock_client:
            await svc.grant_permissions_to_files(
                ["files/a.txt", "files/b.txt"], "my-toolset"
            )

        mock_client.grant_permissions.assert_awaited_once_with(
            ["files/a.txt", "files/b.txt"], "my-toolset"
        )
