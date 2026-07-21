"""URL sanitization for the logging content rule (design #434 / issue #436).

Query strings, fragments, and userinfo are where secrets live in URLs (signed-URL
tokens, API keys, ``user:pass@`` credentials). Every URL that ends up in a log line
or user-facing error message must pass through :func:`sanitize_url_for_log` first.
"""

from urllib.parse import urlsplit, urlunsplit


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
