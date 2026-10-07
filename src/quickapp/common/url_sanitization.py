"""URL sanitization for the logging content rule (design #434 / issue #436).

Query strings, fragments, and userinfo are where secrets live in URLs (signed-URL
tokens, API keys, ``user:pass@`` credentials), and a ``data:`` URI carries its whole
payload inline. Every URL that ends up in a log line or in a model- or user-facing
message must pass through :func:`sanitize_url` first.
"""

from urllib.parse import urlsplit, urlunsplit

# Bound the result so an oversized URL stays a short hint instead of flooding a log line
# or overflowing the next orchestrator request.
_MAX_URL_LENGTH = 200


def sanitize_url(url: str) -> str:
    """Strip a URL to scheme, host, and path, bounded to a fixed length.

    Query strings and fragments — where signed-URL tokens live — are dropped, along with
    any userinfo (``user:pass@``). A relative DIAL path (``files/...``) has no scheme or
    host and is returned with only its query/fragment removed. A ``data:`` URI keeps just
    its header. Anything still over the budget is cut with a trailing ``…``.
    """
    if not url:
        return url
    stripped = _strip_url(url)
    return stripped if len(stripped) <= _MAX_URL_LENGTH else f"{stripped[:_MAX_URL_LENGTH]}…"


def _strip_url(url: str) -> str:
    """Reduce a URL to scheme, host, and path, or a ``data:`` URI to its header; a URL that
    cannot be parsed falls back to the substring before the first ``?`` / ``#``."""
    # A data: URI's payload lives in the path, so scheme/host/path stripping would keep it
    # verbatim. Locate the header without copying the (possibly multi-MB) payload.
    if url[:5].lower() == "data:":
        comma = url.find(",", 5)
        if comma != -1:  # no comma: malformed, fall through to the generic path
            return f"data:{url[5:comma]},…"
    try:
        split = urlsplit(url)
    except ValueError:
        return url.split("?", 1)[0].split("#", 1)[0]
    # Rebuild the netloc from hostname + port only — split.netloc would carry
    # userinfo (user:pass@) straight into the log line.
    host = split.hostname or ""
    netloc = f"{host}:{split.port}" if split.port else host
    return urlunsplit((split.scheme, netloc, split.path, "", ""))
