import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client.types.metadata import FileMetadata

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.external_fetch.external_url_fetcher import (
    ExternalFetchDisabledError,
    ExternalFetchError,
    ExternalUrlFetcher,
    FetchedBytes,
)
from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services.dial_downloader import DialDownloader
from quickapp.file_transfer._file_loader_service import FileLoaderService

DIAL_URL = "https://dial.example.com"


def _settings() -> MagicMock:
    s = MagicMock(spec=DialSettings)
    s.url = DIAL_URL
    return s


def _metadata(etag: str = "abc123") -> MagicMock:
    md = MagicMock(spec=FileMetadata)
    md.etag = etag
    return md


def _make_loader(
    dial_downloader: MagicMock | None = None,
    fetcher: MagicMock | None = None,
    state_holder: StateHolder | None = None,
) -> FileLoaderService:
    return FileLoaderService(
        dial_downloader=dial_downloader or MagicMock(spec=DialDownloader),
        external_fetcher=fetcher or MagicMock(spec=ExternalUrlFetcher),
        state_holder=state_holder or StateHolder(),
        dial_settings=_settings(),
    )


@pytest.mark.asyncio
async def test_dial_url_dispatches_to_dial_downloader():
    dial_dl = MagicMock(spec=DialDownloader)
    dial_dl.fetch = AsyncMock(return_value=(b"dial-bytes", _metadata()))
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock()

    loader = _make_loader(dial_downloader=dial_dl, fetcher=fetcher)
    result = await loader.load("files/bucket/x.pdf")

    assert result == b"dial-bytes"
    dial_dl.fetch.assert_awaited_once_with("files/bucket/x.pdf")
    fetcher.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_url_dispatches_to_fetcher():
    dial_dl = MagicMock(spec=DialDownloader)
    dial_dl.fetch = AsyncMock()
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(
        return_value=FetchedBytes(data=b"ext-bytes", content_type="text/plain", filename="x.txt")
    )

    loader = _make_loader(dial_downloader=dial_dl, fetcher=fetcher)
    result = await loader.load("https://example.com/x.txt")

    assert result == b"ext-bytes"
    fetcher.fetch.assert_awaited_once_with("https://example.com/x.txt")
    dial_dl.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_url_raises_invalid_param():
    loader = _make_loader()
    with pytest.raises(InvalidToolCallParameterException):
        await loader.load("file:///etc/passwd")


@pytest.mark.asyncio
async def test_second_call_returns_from_state_holder_cache():
    dial_dl = MagicMock(spec=DialDownloader)
    dial_dl.fetch = AsyncMock(return_value=(b"first", _metadata()))
    holder = StateHolder()

    loader = _make_loader(dial_downloader=dial_dl, state_holder=holder)
    first = await loader.load("files/x.pdf")
    second = await loader.load("files/x.pdf")

    assert first == second == b"first"
    dial_dl.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_dial_load_populates_state_holder_metadata():
    """Regression: DialFileService.download_file readers (e.g. _edit_file_tool
    for the etag) must see metadata when the bytes were cached by the loader.
    Without this, edit_file silently falls back to if_none_match="*" and the
    DIAL upload trips an EtagMismatchError surfaced to the agent as a
    confusing "file changed concurrently; re-read and retry"."""
    metadata = _metadata(etag="etag-xyz")
    dial_dl = MagicMock(spec=DialDownloader)
    dial_dl.fetch = AsyncMock(return_value=(b"first", metadata))
    holder = StateHolder()

    loader = _make_loader(dial_downloader=dial_dl, state_holder=holder)
    await loader.load("files/x.pdf")

    assert holder.get_file_data(url="files/x.pdf") == b"first"
    assert holder.get_file_metadata("files/x.pdf") is metadata


@pytest.mark.asyncio
async def test_external_load_leaves_state_holder_metadata_unset():
    """External fetches don't have a DIAL FileMetadata; the cache entry should
    just carry bytes, not a placeholder metadata object."""
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(
        return_value=FetchedBytes(data=b"ext", content_type="text/plain", filename="x.txt")
    )
    holder = StateHolder()
    loader = _make_loader(fetcher=fetcher, state_holder=holder)
    await loader.load("https://example.com/x.txt")

    assert holder.get_file_data(url="https://example.com/x.txt") == b"ext"
    assert holder.get_file_metadata("https://example.com/x.txt") is None


@pytest.mark.asyncio
async def test_dial_absolute_url_classified_as_dial_branch():
    dial_dl = MagicMock(spec=DialDownloader)
    dial_dl.fetch = AsyncMock(return_value=(b"dial", _metadata()))
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock()

    loader = _make_loader(dial_downloader=dial_dl, fetcher=fetcher)
    result = await loader.load(f"{DIAL_URL}/v1/files/bucket/x.pdf")

    assert result == b"dial"
    dial_dl.fetch.assert_awaited_once()
    fetcher.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_load_same_url_dedupes_fetch():
    fetch_started = asyncio.Event()
    release_fetch = asyncio.Event()
    md = _metadata()

    async def slow_fetch(_url: str) -> tuple[bytes, MagicMock]:
        fetch_started.set()
        await release_fetch.wait()
        return b"dial-bytes", md

    dial_dl = MagicMock(spec=DialDownloader)
    dial_dl.fetch = AsyncMock(side_effect=slow_fetch)

    loader = _make_loader(dial_downloader=dial_dl)

    first_call = asyncio.create_task(loader.load("files/x.pdf"))
    await fetch_started.wait()
    second_call = asyncio.create_task(loader.load("files/x.pdf"))
    await asyncio.sleep(0)
    release_fetch.set()
    first, second = await asyncio.gather(first_call, second_call)

    assert first == second == b"dial-bytes"
    dial_dl.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_load_allows_retry():
    dial_dl = MagicMock(spec=DialDownloader)
    dial_dl.fetch = AsyncMock(side_effect=[RuntimeError("boom"), (b"second", _metadata())])

    loader = _make_loader(dial_downloader=dial_dl)

    with pytest.raises(RuntimeError, match="boom"):
        await loader.load("files/x.pdf")

    second = await loader.load("files/x.pdf")
    assert second == b"second"
    assert dial_dl.fetch.await_count == 2


@pytest.mark.asyncio
async def test_external_fetch_error_translated_to_invalid_param():
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(
        side_effect=ExternalFetchError(reason="size_limit", url="https://example.com/big")
    )
    loader = _make_loader(fetcher=fetcher)

    with pytest.raises(InvalidToolCallParameterException) as excinfo:
        await loader.load("https://example.com/big", parameter_name="data")
    assert excinfo.value.parameter_name == "data"


@pytest.mark.asyncio
async def test_external_disabled_error_translated_to_invalid_param():
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(
        side_effect=ExternalFetchDisabledError(reason="admin", url="https://example.com/x")
    )
    loader = _make_loader(fetcher=fetcher)

    with pytest.raises(InvalidToolCallParameterException) as excinfo:
        await loader.load("https://example.com/x", parameter_name="content")
    assert excinfo.value.parameter_name == "content"
