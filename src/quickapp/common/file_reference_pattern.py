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
