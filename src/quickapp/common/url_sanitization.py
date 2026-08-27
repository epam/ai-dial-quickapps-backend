"""URL sanitization for the logging content rule (design #434 / issue #436).

Query strings, fragments, and userinfo are where secrets live in URLs (signed-URL
tokens, API keys, ``user:pass@`` credentials). Every URL that ends up in a log line
or user-facing error message must pass through :func:`sanitize_url_for_log` first.

Size is the second hazard (issue #527): a ``data:`` URI carries the whole file inline,
so echoing one verbatim writes megabytes into a log line — or, when the error message
travels back to the model as retry guidance, blows the orchestrator's context window.
Every result is therefore collapsed or capped before it leaves this module.
"""

from urllib.parse import urlsplit, urlunsplit

# Chosen so that no legitimate reference is ever cut: DIAL caps a resource id at 1024
# bytes, and a UTF-8 string is never longer in characters than in bytes. Truncation drops
# the tail, which is where the filename lives, so only genuinely abusive values (inlined
# payloads) should reach it. Deliberately a local constant rather than an import from
# ``url_classification`` — that module imports this one, and the two limits answer to
# different owners even where the number agrees.
_MAX_SANITIZED_URL_CHARS = 1024

# Ends with the same "…[truncated" that ``payload_logging`` uses, so a cut value reads the
# same whichever channel emitted it, then adds the original length — for a URL the size is
# itself the diagnostic.
_TRUNCATION_SUFFIX = "…[truncated, {length} chars total]"

_DATA_URI_SCHEME = "data:"


def _truncate(value: str) -> str:
    if len(value) <= _MAX_SANITIZED_URL_CHARS:
        return value
    suffix = _TRUNCATION_SUFFIX.format(length=len(value))
    return f"{value[:_MAX_SANITIZED_URL_CHARS]}{suffix}"


def _summarize_data_uri(url: str) -> str:
    """Collapse ``data:<mime>;base64,<payload>`` to its header plus the payload size.

    The header identifies the file well enough to debug with; the payload is the file
    itself and must never be reproduced.
    """
    header, separator, payload = url.partition(",")
    if not separator:
        return _truncate(header)
    return f"{_truncate(header)},<{len(payload)} chars>"


def sanitize_url_for_log(url: str) -> str:
    """Strip a URL to scheme, host, and path for logging (content rule, issue #436).

    Query strings and fragments — where signed-URL tokens live — are dropped, along with
    any userinfo (``user:pass@``). A relative DIAL path (``files/...``) has no scheme or
    host and is returned with only its query/fragment removed. A URL that cannot be parsed
    falls back to the substring before the first ``?`` / ``#``.

    A ``data:`` URI is collapsed to its media-type header plus a payload size, and every
    other result is capped at :data:`_MAX_SANITIZED_URL_CHARS` (issue #527).
    """
    if not url:
        return url
    # Checked before parsing: a data: URI can be megabytes, and there is nothing in its
    # payload worth splitting. Leading whitespace is tolerated so a padded value is still
    # collapsed rather than merely capped.
    stripped = url.lstrip()
    if stripped[: len(_DATA_URI_SCHEME)].lower() == _DATA_URI_SCHEME:
        return _summarize_data_uri(stripped)
    try:
        split = urlsplit(url)
    except ValueError:
        return _truncate(url.split("?", 1)[0].split("#", 1)[0])
    # Rebuild the netloc from hostname + port only — split.netloc would carry
    # userinfo (user:pass@) straight into the log line.
    host = split.hostname or ""
    netloc = f"{host}:{split.port}" if split.port else host
    return _truncate(urlunsplit((split.scheme, netloc, split.path, "", "")))
