"""URL sanitization for the logging content rule (design #434 / issue #436).

Query strings, fragments, and userinfo are where secrets live in URLs (signed-URL
tokens, API keys, ``user:pass@`` credentials). Every URL that ends up in a log line
or user-facing error message must pass through :func:`sanitize_url_for_log` first.

A URL headed into a **model- or user-facing message** must additionally pass through
:func:`sanitize_url_for_message`, which caps the length so an oversized rejected
argument cannot overflow the next orchestrator request (issue #578).
"""

from urllib.parse import urlsplit, urlunsplit

# A ``data:`` URI carries its whole payload in the path, so log sanitization keeps it
# verbatim; cap message-bound URLs so a rejected argument stays a short retry hint.
_MAX_MESSAGE_URL_LENGTH = 200


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
    # Rebuild the netloc from hostname + port only — split.netloc would carry
    # userinfo (user:pass@) straight into the log line.
    host = split.hostname or ""
    netloc = f"{host}:{split.port}" if split.port else host
    return urlunsplit((split.scheme, netloc, split.path, "", ""))


def _collapse_data_uri(url: str) -> str | None:
    """Collapse a ``data:`` URI to ``data:<header>,<N chars>``; ``None`` if not one.

    The base64 payload lives in the path, so :func:`sanitize_url_for_log` keeps it
    verbatim. Locate the header without copying the (possibly multi-MB) payload: only its
    length is needed.
    """
    if url[:5].lower() != "data:":
        return None
    comma = url.find(",", 5)
    if comma == -1:  # malformed: no comma separating header from payload
        return None
    return f"data:{url[5:comma]},<{len(url) - comma - 1} chars>"


def sanitize_url_for_message(url: str, max_length: int = _MAX_MESSAGE_URL_LENGTH) -> str:
    """Sanitize a URL for a model- or user-facing message, with a hard length budget.

    Strips secrets like :func:`sanitize_url_for_log`, but bounded so an oversized rejected
    argument cannot overflow the next orchestrator request (issue #578). A ``data:`` URI is
    collapsed to ``data:<header>,<N chars>``; any result still over ``max_length`` is cut to
    that budget with an explicit ``…(truncated, N chars)`` marker, so the model can still
    tell which argument it got wrong.
    """
    if not url:
        return url
    collapsed = _collapse_data_uri(url)
    sanitized = collapsed if collapsed is not None else sanitize_url_for_log(url)
    if len(sanitized) > max_length:
        return f"{sanitized[:max_length]}…(truncated, {len(sanitized)} chars)"
    return sanitized
