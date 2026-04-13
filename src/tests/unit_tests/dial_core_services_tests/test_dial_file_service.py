from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services.dial_file_service import DialFileService
from tests.unit_tests.common.common import mock_dial_core_client_factory


def _make_service(factory: MagicMock, state_holder: StateHolder | None = None) -> DialFileService:
    return DialFileService(state_holder or StateHolder(), PerformanceTimer(), factory)


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_cache_miss_downloads_and_stores(self):
        mock_client = AsyncMock()
        mock_client.get_metadata.return_value = {"contentLength": 100}
        mock_client.get_file.return_value = b"file content"
        factory, _ = mock_dial_core_client_factory(mock_client)

        result = await _make_service(factory).download_file("files/test.txt")

        assert result == b"file content"
        mock_client.get_file.assert_awaited_once_with("files/test.txt")

    @pytest.mark.asyncio
    async def test_cache_hit_returns_from_state(self):
        holder = StateHolder()
        holder.store_file_data("files/cached.txt", b"cached content")
        factory = MagicMock()

        result = await _make_service(factory, state_holder=holder).download_file("files/cached.txt")

        assert result == b"cached content"
        factory.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_exceeds_size_limit_raises_error(self):
        mock_client = AsyncMock()
        mock_client.get_metadata.return_value = {"contentLength": 11 * 1024 * 1024}
        factory, _ = mock_dial_core_client_factory(mock_client)

        with pytest.raises(ValueError, match="exceeds the limit"):
            await _make_service(factory).download_file("files/huge.bin")


class TestGrantPermissions:
    @pytest.mark.asyncio
    async def test_grant_permissions_calls_client(self):
        factory, mock_client = mock_dial_core_client_factory()

        await _make_service(factory).grant_permissions_to_files(
            ["files/a.txt", "files/b.txt"], "my-toolset"
        )

        mock_client.grant_permissions.assert_awaited_once_with(
            ["files/a.txt", "files/b.txt"], "my-toolset"
        )
