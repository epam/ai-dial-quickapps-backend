from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.file_loader_size_limit_resolver import FileLoaderSizeLimitResolver
from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services.dial_file_service import DialFileService

DEFAULT_LIMIT = 10 * 1024 * 1024


def _make_mock_dial_client(
    content_length: int = 100,
    file_content: bytes = b"file content",
) -> MagicMock:
    mock_metadata = MagicMock()
    mock_metadata.content_length = content_length

    mock_download_result = MagicMock()
    mock_download_result.aget_content = AsyncMock(return_value=file_content)

    mock_files = MagicMock()
    mock_files.get_metadata = AsyncMock(return_value=mock_metadata)
    mock_files.download = AsyncMock(return_value=mock_download_result)

    mock_resource_permissions = MagicMock()
    mock_resource_permissions.grant = AsyncMock(return_value=None)

    mock_dial_client = MagicMock()
    mock_dial_client.files = mock_files
    mock_dial_client.resource_permissions = mock_resource_permissions
    return mock_dial_client


def _make_resolver(size_limit: int = DEFAULT_LIMIT) -> MagicMock:
    resolver = MagicMock(spec=FileLoaderSizeLimitResolver)
    resolver.resolve.return_value = size_limit
    return resolver


def _make_service(
    dial_client: MagicMock | None = None,
    state_holder: StateHolder | None = None,
    size_limit_resolver: MagicMock | None = None,
) -> DialFileService:
    return DialFileService(
        dial_client=dial_client or _make_mock_dial_client(),
        state_holder=state_holder or StateHolder(),
        size_limit_resolver=size_limit_resolver or _make_resolver(),
    )


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_cache_miss_downloads_and_stores(self):
        file_bytes = b"file content"
        mock_dial_client = _make_mock_dial_client(content_length=100, file_content=file_bytes)
        svc = _make_service(dial_client=mock_dial_client)

        result = await svc.download_file("files/test.txt")

        assert result == file_bytes
        mock_dial_client.files.get_metadata.assert_awaited_once_with("files/test.txt")
        mock_dial_client.files.download.assert_awaited_once_with("files/test.txt")

    @pytest.mark.asyncio
    async def test_cache_hit_returns_from_state(self):
        holder = StateHolder()
        holder.store_file_data("files/cached.txt", b"cached content")
        mock_dial_client = _make_mock_dial_client()
        svc = _make_service(dial_client=mock_dial_client, state_holder=holder)

        result = await svc.download_file("files/cached.txt")

        assert result == b"cached content"
        mock_dial_client.files.get_metadata.assert_not_called()
        mock_dial_client.files.download.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_exceeds_size_limit_raises_error(self):
        mock_dial_client = _make_mock_dial_client(content_length=11 * 1024 * 1024)
        svc = _make_service(dial_client=mock_dial_client)

        with pytest.raises(ValueError, match="exceeds the limit"):
            await svc.download_file("files/huge.bin")

        mock_dial_client.files.download.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolver_value_drives_limit(self):
        mock_dial_client = _make_mock_dial_client(content_length=2048)
        svc = _make_service(
            dial_client=mock_dial_client,
            size_limit_resolver=_make_resolver(size_limit=1024),
        )

        with pytest.raises(ValueError, match="exceeds the limit of 1024"):
            await svc.download_file("files/medium.bin")


class TestGrantPermissions:
    @pytest.mark.asyncio
    async def test_grant_permissions_calls_client(self):
        mock_dial_client = _make_mock_dial_client()
        svc = _make_service(dial_client=mock_dial_client)

        await svc.grant_permissions_to_files(["files/a.txt", "files/b.txt"], "my-toolset")

        mock_dial_client.resource_permissions.grant.assert_awaited_once_with(
            resources=["files/a.txt", "files/b.txt"],
            receiver="my-toolset",
        )
