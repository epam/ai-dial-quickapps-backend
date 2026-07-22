"""Shared front-half for the built-in ``internal_web_fetch`` tool.

Both of the tool's branches (read inline / save to workspace) need the same
steps before they diverge: classify the URL, reject DIAL / unsupported schemes
with actionable errors, fetch the bytes through the single egress point
(:class:`ExternalUrlFetcher`), and decide whether the payload is textual. This
helper owns exactly that shared half; the tool decides what to do with the
returned :class:`FetchedBytes`.
"""

import logging
from email.message import Message

from injector import inject

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.url_classification import UrlScheme, classify_url, unsupported_scheme_error
from quickapp.shared.external_fetch.external_url_fetcher import (
    ExternalFetchDisabledError,
    ExternalFetchError,
    ExternalUrlFetcher,
    FetchedBytes,
)

logger = logging.getLogger(__name__)

# Non-``text/*`` MIME types that are nevertheless textual and safe to decode /
# inline. Kept small and explicit in phase-1 (no content-sniffing library).
_TEXTUAL_APPLICATION_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/xhtml+xml",
        "application/javascript",
        "application/ecmascript",
        "application/x-yaml",
        "application/yaml",
        "application/x-www-form-urlencoded",
        "application/csv",
    }
)


def _base_content_type(content_type: str | None) -> str | None:
    """Return the lower-cased MIME type without parameters (``; charset=...``)."""
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower()


def _charset(content_type: str | None) -> str | None:
    if not content_type:
        return None
    msg = Message()
    msg["content-type"] = content_type
    charset = msg.get_param("charset")
    return charset if isinstance(charset, str) and charset else None


@inject
class WebContentFetcher:
    """Classify + fetch + decode helper shared by the built-in web tools.

    A thin wrapper over :class:`ExternalUrlFetcher` that maps its scheme
    classification and egress errors into ``InvalidToolCallParameterException``
    (the tool-facing error shape), mirroring ``FileLoaderService``. The egress
    policy itself (admin switch, per-app opt-out, host allowlist, SSRF guard,
    size / redirect / timeout caps) lives entirely in the fetcher and is reused
    verbatim.
    """

    def __init__(
        self,
        external_fetcher: ExternalUrlFetcher,
        dial_settings: DialSettings,
    ) -> None:
        self.__external_fetcher = external_fetcher
        self.__dial_url = dial_settings.url
        # Fetch cache, request-scoped because this class is bound request-scoped:
        # a re-call for the same URL within one request — e.g. a save_path call
        # after a truncated inline read — must not re-download.
        self.__fetched_by_url: dict[str, FetchedBytes] = {}

    async def fetch_external(self, url: str, parameter_name: str = "url") -> FetchedBytes:
        """Classify ``url`` and fetch it, or raise a tool-facing parameter error.

        * DIAL URL or agent-home-relative path -> rejected: the resource is
          already in DIAL storage and the fetch tools are for *external*
          retrieval only. The message stays tool-neutral — which workspace
          tools exist varies per app.
        * Unsupported scheme -> the canonical unsupported-scheme error.
        * External -> fetched through :class:`ExternalUrlFetcher`; its
          ``ExternalFetchError`` / ``ExternalFetchDisabledError`` (egress
          disabled, host not allowed, SSRF, size, timeout, transport) are
          re-raised as ``InvalidToolCallParameterException`` carrying the
          existing operator/builder messages. Successful fetches are cached for
          the lifetime of this (request-scoped) instance, keyed by URL.
        """
        scheme = classify_url(url, self.__dial_url)
        if scheme in (UrlScheme.DIAL, UrlScheme.DIAL_APPDIR_RELATIVE):
            raise InvalidToolCallParameterException(
                parameter_name,
                f"URL {url} already points to a file in DIAL storage and does not "
                "need fetching. Access it with your available workspace tools.",
            )
        if scheme == UrlScheme.UNSUPPORTED:
            raise unsupported_scheme_error(url, parameter_name)

        cached = self.__fetched_by_url.get(url)
        if cached is not None:
            return cached

        try:
            fetched = await self.__external_fetcher.fetch(url)
        except (ExternalFetchError, ExternalFetchDisabledError) as exc:
            raise InvalidToolCallParameterException(parameter_name, str(exc)) from exc

        self.__fetched_by_url[url] = fetched
        return fetched

    @staticmethod
    def is_textual(content_type: str | None) -> bool:
        """Whether a payload with this ``content_type`` can be decoded as text.

        Textual: any ``text/*`` type, an explicit allowlisted ``application/*``
        type, or a structured-syntax suffix (``+json`` / ``+xml``). A missing
        content type is treated as **non-textual** — phase-1 fails closed rather
        than risk decoding binary bytes into the LLM context.
        """
        base = _base_content_type(content_type)
        if base is None:
            return False
        if base.startswith("text/"):
            return True
        if base in _TEXTUAL_APPLICATION_TYPES:
            return True
        return base.endswith("+json") or base.endswith("+xml")

    @staticmethod
    def decode(data: bytes, content_type: str | None) -> str:
        """Decode ``data`` using the response charset, defaulting to UTF-8.

        Uses ``errors="replace"`` so an incorrectly-declared charset degrades to
        replacement characters rather than raising — the caller has already
        decided the payload is textual.
        """
        charset = _charset(content_type) or "utf-8"
        try:
            return data.decode(charset, errors="replace")
        except LookupError:
            return data.decode("utf-8", errors="replace")
