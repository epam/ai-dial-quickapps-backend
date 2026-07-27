"""Fetch + scheme-classify helper for the built-in ``internal_web_fetch`` tool.

Wraps :class:`ExternalUrlFetcher` with URL-scheme classification and a
request-scoped fetch cache. It raises only domain errors — its own
:class:`WebContentFetchError`, or the fetcher's ``ExternalFetchError`` /
``ExternalFetchDisabledError`` — leaving the tool to translate them into its
parameter-error shape.
"""

from injector import inject

from quickapp.common.dial_settings import DialSettings
from quickapp.common.url_classification import UrlScheme, classify_url
from quickapp.common.url_sanitization import sanitize_url_for_log
from quickapp.shared.external_fetch.external_url_fetcher import ExternalUrlFetcher, FetchedBytes


class WebContentFetchError(Exception):
    """A URL cannot be fetched because it is not an external http(s) resource."""


@inject
class WebContentFetcher:
    """Classify + fetch helper shared by the built-in web tools.

    Reuses the egress policy of :class:`ExternalUrlFetcher` (admin switch,
    per-app opt-out, host allowlist, SSRF guard, size / redirect / timeout caps)
    verbatim; adds scheme classification and a per-request fetch cache.
    """

    def __init__(self, external_fetcher: ExternalUrlFetcher, dial_settings: DialSettings) -> None:
        self.__external_fetcher = external_fetcher
        self.__dial_url = dial_settings.url
        # Request-scoped (this class is bound request-scoped) so a re-call for the
        # same URL within one request does not re-download.
        self.__fetched_by_url: dict[str, FetchedBytes] = {}

    async def fetch_external(self, url: str) -> FetchedBytes:
        """Classify ``url`` and fetch it, caching successful fetches per request.

        Raises :class:`WebContentFetchError` for DIAL / unsupported URLs and
        propagates ``ExternalFetchError`` / ``ExternalFetchDisabledError`` for
        egress failures.
        """
        scheme = classify_url(url, self.__dial_url)
        if scheme in (UrlScheme.DIAL, UrlScheme.DIAL_APPDIR_RELATIVE):
            raise WebContentFetchError(
                f"URL {url} already points to a file in DIAL storage and does not "
                "need fetching. Access it with your available workspace tools."
            )
        if scheme == UrlScheme.UNSUPPORTED:
            raise WebContentFetchError(
                f"URL scheme not supported: {sanitize_url_for_log(url)}. "
                "Only http(s) URLs can be fetched."
            )

        cached = self.__fetched_by_url.get(url)
        if cached is not None:
            return cached
        fetched = await self.__external_fetcher.fetch(url)
        self.__fetched_by_url[url] = fetched
        return fetched
