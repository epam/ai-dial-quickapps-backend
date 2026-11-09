from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.dial_core_services.dial_downloader import DialDownloader
from quickapp.dial_core_services.storage._v1_file_storage import V1FileStorage
from quickapp.dial_core_services.storage.file_storage import FileStorage
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)

DEFAULT_LIMIT = 10 * 1024 * 1024


def _make_mock_dial_client(
    content_length: int = 100,
    file_content: bytes = b"file content",
) -> MagicMock:
    metadata = MagicMock()
    metadata.content_length = content_length

    download_result = MagicMock()
    download_result.aget_content = AsyncMock(return_value=file_content)

    files = MagicMock()
    files.get_metadata = AsyncMock(return_value=metadata)
    files.download = AsyncMock(return_value=download_result)

    client = MagicMock()
    client.files = files
    return client


def _make_resolver(size_limit: int = DEFAULT_LIMIT) -> MagicMock:
    resolver = MagicMock(spec=FileLoadingSizeLimitResolver)
    resolver.resolve.return_value = size_limit
    return resolver


def _make_downloader(
    dial_client: MagicMock | None = None,
    size_limit_resolver: MagicMock | None = None,
) -> DialDownloader:
    return DialDownloader(
        storage=V1FileStorage(dial_client or _make_mock_dial_client()),
        size_limit_resolver=size_limit_resolver or _make_resolver(),
    )


@pytest.mark.asyncio
async def test_fetch_returns_bytes_and_metadata():
    client = _make_mock_dial_client(content_length=100, file_content=b"hello")
    downloader = _make_downloader(dial_client=client)

    data, metadata = await downloader.fetch("files/x.txt")

    assert data == b"hello"
    assert metadata is client.files.get_metadata.return_value
    client.files.get_metadata.assert_awaited_once_with("files/x.txt")
    client.files.download.assert_awaited_once_with("files/x.txt")


@pytest.mark.asyncio
async def test_fetch_rejects_oversize_via_metadata():
    client = _make_mock_dial_client(content_length=11 * 1024 * 1024)
    downloader = _make_downloader(dial_client=client)

    with pytest.raises(ValueError, match="exceeds the limit"):
        await downloader.fetch("files/big.bin")

    client.files.download.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_uses_resolver_value_for_limit():
    client = _make_mock_dial_client(content_length=2048)
    downloader = _make_downloader(
        dial_client=client,
        size_limit_resolver=_make_resolver(size_limit=1024),
    )

    with pytest.raises(ValueError, match="exceeds the limit of 1024"):
        await downloader.fetch("files/medium.bin")


@pytest.mark.asyncio
async def test_fetch_passes_the_resolved_limit_to_the_storage():
    storage = MagicMock(spec=FileStorage)
    storage.download = AsyncMock(return_value=(b"data", MagicMock()))
    downloader = DialDownloader(storage=storage, size_limit_resolver=_make_resolver(1024))

    await downloader.fetch("projects/b/p/files/context/a.csv")

    storage.download.assert_awaited_once_with("projects/b/p/files/context/a.csv", 1024)
