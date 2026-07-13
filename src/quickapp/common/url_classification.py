import re
from enum import Enum
from functools import lru_cache
from urllib.parse import urlsplit

from quickapp.common.exceptions import InvalidToolCallParameterException


class UrlScheme(str, Enum):
    DIAL = "dial"
    EXTERNAL = "external"
    DIAL_APPDIR_RELATIVE = "dial_appdir_relative"
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
    other ``http(s)://`` URL is :attr:`UrlScheme.EXTERNAL`. A schemeless,
    hostless, colon-free path (e.g. ``reports/img.png``) is
    :attr:`UrlScheme.DIAL_APPDIR_RELATIVE` — the agent-home-relative convention spoken by
    the file tools; how (and whether) to resolve it is the
    caller's decision. Anything else (``file:``, ``ftp:``, ``data:``,
    malformed, empty hostname) is :attr:`UrlScheme.UNSUPPORTED`.
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
    if not scheme:
        # A ':' anywhere means scheme-like intent urlsplit could not parse
        # (e.g. '://broken'); a netloc means a protocol-relative '//host' url.
        if split.netloc or not split.path or ":" in url:
            return UrlScheme.UNSUPPORTED
        return UrlScheme.DIAL_APPDIR_RELATIVE
    if scheme not in ("http", "https"):
        return UrlScheme.UNSUPPORTED

    host = (split.hostname or "").lower()
    if not host:
        return UrlScheme.UNSUPPORTED

    dial_host = _dial_host(dial_base_url)
    if dial_host and host == dial_host:
        return UrlScheme.DIAL

    return UrlScheme.EXTERNAL


def unsupported_scheme_error(url: str, parameter_name: str) -> InvalidToolCallParameterException:
    """Build the canonical "URL scheme not supported" exception.

    Centralised so every consumer of :func:`classify_url` raises the same
    message; agents see consistent retry guidance regardless of where the
    rejection happens.
    """
    return InvalidToolCallParameterException(
        parameter_name=parameter_name,
        message=(
            f"URL scheme not supported: {url}. "
            "Only DIAL file paths (e.g. files/bucket/foo.pdf) and "
            "http(s) URLs are accepted."
        ),
    )
