import re

FILE_PATTERN = re.compile(
    r"^/*file:(?:(?P<prefix>base64|url|text|data)::)?(?P<file_url>.+)$", re.IGNORECASE
)

MISSING_FILE_PREFIX_MESSAGE = "Missing required file prefix (data::, base64::, url::, text::)"


def is_unprefixed_file_reference(value: str) -> bool:
    """True for a ``file:`` reference that lacks a recognized marker (e.g. ``file:files/a.pdf``)."""
    m = FILE_PATTERN.match(value)
    return m is not None and not m.group("prefix")


def strip_file_prefix(value: str) -> str:
    """Return the bare file URL/path from a file: reference, or the original string if it is not a file reference.

    The prefix marker is optional in :data:`FILE_PATTERN` so callers can detect and reject a
    prefix-less ``file:`` reference, but only a recognized marker is stripped here — otherwise
    an ordinary path ending in ``file:something`` would be silently shortened.
    """
    m = FILE_PATTERN.match(value)
    if not m or not m.group("prefix"):
        return value
    return m.group("file_url")


def to_file_url_reference(url: str) -> str:
    """Wrap a bare file URL/path as a ``file:url::`` reference — the inverse of
    :func:`strip_file_prefix` for the ``url`` prefix. Use when emitting a file
    reference the model is meant to imitate, so it follows the convention.
    """
    return f"file:url::{url}"
