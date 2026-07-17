import re
from enum import Enum
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from quickapp.common.exceptions import InvalidToolCallParameterException


class UrlScheme(str, Enum):
    DIAL = "dial"
    EXTERNAL = "external"
    UNSUPPORTED = "unsupported"


_DIAL_RELATIVE_PATH = re.compile(r"^/*files/", re.IGNORECASE)


@lru_cache(maxsize=8)
def _dial_host(dial_base_url: str) -> str:
    try:
        return (urlsplit(dial_base_url).hostname or "").lower()
    except ValueError:
        return ""


def classify_url(url: str, dial_base_url: str) -> UrlScheme:
    """Classify a file reference URL against the configured DIAL base URL.

    A bare DIAL relative path (e.g. ``files/bucket/foo.pdf``) or an absolute URL
    whose host matches the configured DIAL host is :attr:`UrlScheme.DIAL`. Any
    other ``http(s)://`` URL is :attr:`UrlScheme.EXTERNAL`. Anything else
    (``file:``, ``ftp:``, ``data:``, malformed, empty hostname) is
    :attr:`UrlScheme.UNSUPPORTED`.
    """
    if not url:
        return UrlScheme.UNSUPPORTED

    if _DIAL_RELATIVE_PATH.match(url):
        return UrlScheme.DIAL

    try:
        split = urlsplit(url)
    except ValueError:
        return UrlScheme.UNSUPPORTED

    scheme = (split.scheme or "").lower()
    if scheme not in ("http", "https"):
        return UrlScheme.UNSUPPORTED

    host = (split.hostname or "").lower()
    if not host:
        return UrlScheme.UNSUPPORTED

    dial_host = _dial_host(dial_base_url)
    if dial_host and host == dial_host:
        return UrlScheme.DIAL

    return UrlScheme.EXTERNAL


def sanitize_url_for_log(url: str) -> str:
    """Strip a URL to scheme, host, and path for logging (content rule, issue #436).

    Query strings and fragments — where signed-URL tokens live — are dropped, along with
    any userinfo (``user:pass@``). A relative DIAL path (``files/...``) has no scheme or
    host and is returned with only its query/fragment removed. A URL that cannot be parsed
    falls back to the substring before the first ``?`` / ``#``.
    """
    if not url:
        return url
    try:
        split = urlsplit(url)
    except ValueError:
        return url.split("?", 1)[0].split("#", 1)[0]
    host = split.hostname or ""
    netloc = f"{host}:{split.port}" if split.port else host
    return urlunsplit((split.scheme, netloc, split.path, "", ""))


def unsupported_scheme_error(url: str, parameter_name: str) -> InvalidToolCallParameterException:
    """Build the canonical "URL scheme not supported" exception.

    Centralised so every consumer of :func:`classify_url` raises the same
    message; agents see consistent retry guidance regardless of where the
    rejection happens.
    """
    return InvalidToolCallParameterException(
        parameter_name=parameter_name,
        message=(
            f"URL scheme not supported: {sanitize_url_for_log(url)}. "
            "Only DIAL file paths (e.g. files/bucket/foo.pdf) and "
            "http(s) URLs are accepted."
        ),
    )
