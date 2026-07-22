from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.shared.external_fetch.external_url_fetcher import (
    ExternalFetchDisabledError,
    ExternalFetchError,
    FetchedBytes,
)
from quickapp.shared.external_fetch.web_content_fetcher import WebContentFetcher

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
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await fetcher.fetch_external("files/bucket/doc.md")
        assert exc.value.parameter_name == "url"
        assert "DIAL storage" in exc.value.message
        # Guidance must stay tool-neutral: no other tool availability is assumed.
        assert "internal_file" not in exc.value.message

    @pytest.mark.asyncio
    async def test_home_relative_path_rejected_as_already_in_storage(self):
        fetcher = _make_fetcher()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await fetcher.fetch_external("reports/img.png")
        assert exc.value.parameter_name == "url"
        assert "DIAL storage" in exc.value.message

    @pytest.mark.asyncio
    async def test_repeat_fetch_served_from_request_cache(self):
        fetched = FetchedBytes(data=b"hello", content_type="text/plain", filename="a.txt")
        external = MagicMock()
        external.fetch = AsyncMock(return_value=fetched)
        dial_settings = MagicMock()
        dial_settings.url = _DIAL_URL
        fetcher = WebContentFetcher(external_fetcher=external, dial_settings=dial_settings)
        first = await fetcher.fetch_external("https://example.com/a.txt")
        second = await fetcher.fetch_external("https://example.com/a.txt")
        assert second is first
        external.fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_errors_not_cached(self):
        external = MagicMock()
        external.fetch = AsyncMock(
            side_effect=ExternalFetchError(reason="size_limit", url="https://x.com")
        )
        dial_settings = MagicMock()
        dial_settings.url = _DIAL_URL
        fetcher = WebContentFetcher(external_fetcher=external, dial_settings=dial_settings)
        with pytest.raises(InvalidToolCallParameterException):
            await fetcher.fetch_external("https://x.com")
        with pytest.raises(InvalidToolCallParameterException):
            await fetcher.fetch_external("https://x.com")
        assert external.fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_dial_host_url_rejected(self):
        fetcher = _make_fetcher()
        with pytest.raises(InvalidToolCallParameterException):
            await fetcher.fetch_external(f"{_DIAL_URL}/v1/files/x/doc.md")

    @pytest.mark.asyncio
    async def test_unsupported_scheme_rejected(self):
        fetcher = _make_fetcher()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await fetcher.fetch_external("ftp://example.com/x")
        assert "scheme not supported" in exc.value.message

    @pytest.mark.asyncio
    async def test_egress_disabled_wrapped_as_parameter_error(self):
        fetcher = _make_fetcher(ExternalFetchDisabledError(reason="admin", url="https://x.com"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await fetcher.fetch_external("https://x.com")
        assert exc.value.parameter_name == "url"
        assert "EXTERNAL_URL_FETCH_ENABLED" in exc.value.message

    @pytest.mark.asyncio
    async def test_fetch_error_wrapped_as_parameter_error(self):
        fetcher = _make_fetcher(ExternalFetchError(reason="size_limit", url="https://x.com"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await fetcher.fetch_external("https://x.com")
        assert exc.value.parameter_name == "url"

    @pytest.mark.asyncio
    async def test_custom_parameter_name_used(self):
        fetcher = _make_fetcher()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await fetcher.fetch_external("files/b/x", parameter_name="target")
        assert exc.value.parameter_name == "target"


class TestIsTextual:
    @pytest.mark.parametrize(
        "content_type",
        [
            "text/plain",
            "text/markdown; charset=utf-8",
            "text/html",
            "application/json",
            "application/xml",
            "application/vnd.api+json",
            "image/svg+xml",
        ],
    )
    def test_textual(self, content_type):
        assert WebContentFetcher.is_textual(content_type) is True

    @pytest.mark.parametrize(
        "content_type",
        [
            None,
            "application/octet-stream",
            "image/png",
            "application/pdf",
            "application/zip",
        ],
    )
    def test_non_textual(self, content_type):
        assert WebContentFetcher.is_textual(content_type) is False


class TestDecode:
    def test_utf8_default(self):
        assert WebContentFetcher.decode("héllo".encode("utf-8"), "text/plain") == "héllo"

    def test_explicit_charset(self):
        assert (
            WebContentFetcher.decode("héllo".encode("latin-1"), "text/plain; charset=latin-1")
            == "héllo"
        )

    def test_unknown_charset_falls_back_to_utf8(self):
        assert WebContentFetcher.decode(b"hi", "text/plain; charset=not-a-charset") == "hi"

    def test_invalid_bytes_replaced_not_raised(self):
        # Lone continuation byte is invalid UTF-8; replace rather than raise.
        assert WebContentFetcher.decode(b"\xff", "text/plain") == "�"
