import re

FILE_PATTERN = re.compile(
    r"^/*file:(?:(?P<prefix>base64|url|text)::)?(?P<file_url>.+)$", re.IGNORECASE
)


def strip_file_prefix(value: str) -> str:
    """Return the bare file URL/path from a file: reference, or the original string if it is not a file reference."""
    m = FILE_PATTERN.match(value)
    if not m:
        return value
    return m.group("file_url")


def to_file_url_reference(url: str) -> str:
    """Wrap a bare file URL/path as a ``file:url::`` reference — the inverse of
    :func:`strip_file_prefix` for the ``url`` prefix. Use when emitting a file
    reference the model is meant to imitate, so it follows the convention.
    """
    return f"file:url::{url}"
