from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.shared.external_fetch.external_url_fetcher import (
    ExternalFetchDisabledError,
    ExternalFetchError,
    FetchedBytes,
)
from quickapp.shared.external_fetch.web_content_fetcher import (
    WebContentFetcher,
    WebContentFetchError,
)

_DIAL_URL = "https://dial.example.com"


def _make_fetcher(fetch_result: FetchedBytes | Exception | None = None) -> WebContentFetcher:
    external = MagicMock()
    if isinstance(fetch_result, Exception):
        external.fetch = AsyncMock(side_effect=fetch_result)
    else:
        external.fetch = AsyncMock(return_value=fetch_result)
    dial_settings = MagicMock()
    dial_settings.url = _DIAL_URL
    return WebContentFetcher(external_fetcher=external, dial_settings=dial_settings)


class TestFetchExternal:
    @pytest.mark.asyncio
    async def test_external_url_fetched(self):
        fetched = FetchedBytes(data=b"hello", content_type="text/plain", filename="a.txt")
        fetcher = _make_fetcher(fetched)
        result = await fetcher.fetch_external("https://example.com/a.txt")
        assert result is fetched

    @pytest.mark.asyncio
    async def test_dial_relative_path_rejected(self):
        fetcher = _make_fetcher()
        with pytest.raises(WebContentFetchError) as exc:
            await fetcher.fetch_external("files/bucket/doc.md")
        assert "DIAL storage" in str(exc.value)
        # Guidance must stay tool-neutral: no other tool availability is assumed.
        assert "internal_file" not in str(exc.value)

    @pytest.mark.asyncio
    async def test_home_relative_path_rejected_as_already_in_storage(self):
        fetcher = _make_fetcher()
        with pytest.raises(WebContentFetchError) as exc:
            await fetcher.fetch_external("reports/img.png")
        assert "DIAL storage" in str(exc.value)

    @pytest.mark.asyncio
    async def test_dial_host_url_rejected(self):
        fetcher = _make_fetcher()
        with pytest.raises(WebContentFetchError):
            await fetcher.fetch_external(f"{_DIAL_URL}/v1/files/x/doc.md")

    @pytest.mark.asyncio
    async def test_unsupported_scheme_rejected(self):
        fetcher = _make_fetcher()
        with pytest.raises(WebContentFetchError) as exc:
            await fetcher.fetch_external("ftp://example.com/x")
        assert "scheme not supported" in str(exc.value)

    @pytest.mark.asyncio
    async def test_repeat_fetch_served_from_request_cache(self):
        fetched = FetchedBytes(data=b"hello", content_type="text/plain", filename="a.txt")
        fetcher = _make_fetcher(fetched)
        first = await fetcher.fetch_external("https://example.com/a.txt")
        second = await fetcher.fetch_external("https://example.com/a.txt")
        assert second is first

    @pytest.mark.asyncio
    async def test_egress_errors_propagate_and_are_not_cached(self):
        # The fetcher no longer wraps egress errors; they propagate unchanged and
        # a failed fetch is retried on the next call (not cached).
        fetcher = _make_fetcher(ExternalFetchError(reason="size_limit", url="https://x.com"))
        with pytest.raises(ExternalFetchError):
            await fetcher.fetch_external("https://x.com")
        with pytest.raises(ExternalFetchError):
            await fetcher.fetch_external("https://x.com")

    @pytest.mark.asyncio
    async def test_egress_disabled_propagates(self):
        fetcher = _make_fetcher(ExternalFetchDisabledError(reason="admin", url="https://x.com"))
        with pytest.raises(ExternalFetchDisabledError):
            await fetcher.fetch_external("https://x.com")
