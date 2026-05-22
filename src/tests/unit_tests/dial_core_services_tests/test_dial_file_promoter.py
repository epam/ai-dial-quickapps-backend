import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.external_fetch.external_url_fetcher import (
    ExternalFetchError,
    ExternalUrlFetcher,
    FetchedBytes,
)
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter

DIAL_URL = "https://dial.example.com"


def _settings() -> MagicMock:
    s = MagicMock(spec=DialSettings)
    s.url = DIAL_URL
    return s


def _make_metadata(url: str = "https://dial.example.com/v1/files/x", name: str = "x") -> MagicMock:
    meta = MagicMock()
    meta.url = url
    meta.name = name
    meta.content_type = "application/pdf"
    return meta


def _make_promoter(
    files_get_metadata: AsyncMock | None = None,
    fetcher: MagicMock | None = None,
    attachments: MagicMock | None = None,
) -> DialFilePromoter:
    dial_client = MagicMock()
    dial_client.files.get_metadata = files_get_metadata or AsyncMock(return_value=_make_metadata())
    return DialFilePromoter(
        dial_client=dial_client,
        external_fetcher=fetcher or MagicMock(spec=ExternalUrlFetcher),
        attachment_service=attachments or MagicMock(spec=AttachmentService),
        dial_settings=_settings(),
    )


@pytest.mark.asyncio
async def test_dial_branch_reads_metadata_no_upload():
    metadata = _make_metadata(url="https://dial.example.com/v1/files/y.pdf", name="y.pdf")
    get_metadata = AsyncMock(return_value=metadata)
    attachments = MagicMock(spec=AttachmentService)
    attachments.upload_bytes = AsyncMock()

    promoter = _make_promoter(files_get_metadata=get_metadata, attachments=attachments)
    result = await promoter.promote("files/bucket/y.pdf")

    assert result is metadata
    get_metadata.assert_awaited_once_with("files/bucket/y.pdf")
    attachments.upload_bytes.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_branch_fetches_and_uploads():
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(
        return_value=FetchedBytes(data=b"hello", content_type="text/plain", filename="hi.txt")
    )
    attachments = MagicMock(spec=AttachmentService)
    uploaded = _make_metadata(url="https://dial.example.com/v1/files/hi.txt", name="hi.txt")
    attachments.upload_bytes = AsyncMock(return_value=uploaded)

    promoter = _make_promoter(fetcher=fetcher, attachments=attachments)
    result = await promoter.promote("https://example.com/hi.txt")

    assert result is uploaded
    fetcher.fetch.assert_awaited_once_with("https://example.com/hi.txt")
    attachments.upload_bytes.assert_awaited_once_with(
        data=b"hello", content_type="text/plain", filename="hi.txt"
    )


@pytest.mark.asyncio
async def test_second_call_for_same_url_hits_cache():
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(
        return_value=FetchedBytes(data=b"x", content_type="text/plain", filename="x.txt")
    )
    attachments = MagicMock(spec=AttachmentService)
    attachments.upload_bytes = AsyncMock(return_value=_make_metadata())

    promoter = _make_promoter(fetcher=fetcher, attachments=attachments)
    first = await promoter.promote("https://example.com/x.txt")
    second = await promoter.promote("https://example.com/x.txt")

    assert first is second
    fetcher.fetch.assert_awaited_once()
    attachments.upload_bytes.assert_awaited_once()


@pytest.mark.asyncio
async def test_unsupported_url_raises():
    promoter = _make_promoter()
    with pytest.raises(InvalidToolCallParameterException):
        await promoter.promote("ftp://example.com/x")


@pytest.mark.asyncio
async def test_upload_failure_propagates():
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(
        return_value=FetchedBytes(data=b"x", content_type="text/plain", filename="x.txt")
    )
    attachments = MagicMock(spec=AttachmentService)
    attachments.upload_bytes = AsyncMock(side_effect=RuntimeError("upload boom"))

    promoter = _make_promoter(fetcher=fetcher, attachments=attachments)
    with pytest.raises(RuntimeError, match="upload boom"):
        await promoter.promote("https://example.com/x.txt")


@pytest.mark.asyncio
async def test_concurrent_promote_same_url_dedupes_fetch_and_upload():
    fetch_started = asyncio.Event()
    release_fetch = asyncio.Event()

    async def slow_fetch(_url: str) -> FetchedBytes:
        fetch_started.set()
        await release_fetch.wait()
        return FetchedBytes(data=b"x", content_type="text/plain", filename="x.txt")

    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(side_effect=slow_fetch)
    attachments = MagicMock(spec=AttachmentService)
    attachments.upload_bytes = AsyncMock(return_value=_make_metadata())

    promoter = _make_promoter(fetcher=fetcher, attachments=attachments)

    first_call = asyncio.create_task(promoter.promote("https://example.com/x.txt"))
    await fetch_started.wait()
    second_call = asyncio.create_task(promoter.promote("https://example.com/x.txt"))
    await asyncio.sleep(0)
    release_fetch.set()
    first, second = await asyncio.gather(first_call, second_call)

    assert first is second
    fetcher.fetch.assert_awaited_once()
    attachments.upload_bytes.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_promote_allows_retry():
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(
        side_effect=[
            ExternalFetchError(reason="transport", url="https://example.com/x"),
            FetchedBytes(data=b"x", content_type="text/plain", filename="x.txt"),
        ]
    )
    attachments = MagicMock(spec=AttachmentService)
    attachments.upload_bytes = AsyncMock(return_value=_make_metadata())

    promoter = _make_promoter(fetcher=fetcher, attachments=attachments)

    with pytest.raises(InvalidToolCallParameterException):
        await promoter.promote("https://example.com/x")

    result = await promoter.promote("https://example.com/x")
    assert result is not None
    assert fetcher.fetch.await_count == 2


@pytest.mark.asyncio
async def test_external_fetch_error_translated_to_invalid_param():
    fetcher = MagicMock(spec=ExternalUrlFetcher)
    fetcher.fetch = AsyncMock(
        side_effect=ExternalFetchError(reason="ssrf_block", url="https://internal/x")
    )
    promoter = _make_promoter(fetcher=fetcher)

    with pytest.raises(InvalidToolCallParameterException) as excinfo:
        await promoter.promote("https://internal/x", parameter_name="attachment_urls")
    assert excinfo.value.parameter_name == "attachment_urls"
