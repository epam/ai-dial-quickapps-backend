import logging
import mimetypes
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

ALL_MIME_TYPES = "*/*"
_INVALID_TOOLNAME_CHARS_REGEXP: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9_-]")


# Normalize propagation types (split wildcards like 'image/*' for matching)
def matches_type(mime_type: str, allowed_mime_types: Optional[list[str]]) -> bool:
    if mime_type is None or allowed_mime_types is None:
        logger.warning(
            f"The mime_type is None, for the match check. Allowed_mime_types: {allowed_mime_types}"
        )
        return False
    for mt in allowed_mime_types:
        if mt == ALL_MIME_TYPES:  # catch-all wildcard
            return True
        if mt.endswith("/*"):
            if mime_type.startswith(mt[:-1]):  # e.g. "image/*" matches "image/png"
                return True
        elif mime_type == mt:
            return True
    return False


def sanitize_toolname(input_str: str) -> str:
    """
    Sanitizes a string to match the pattern ^[a-zA-Z0-9_-]{1,64}$

    Args:
        input_str: Input string to sanitize

    Returns:
        Sanitized string containing only allowed characters (a-z, A-Z, 0-9, _, -)
        with length 1-64 characters. Returns empty string if no valid characters exist.
    """
    # Step 1: Remove all invalid characters
    sanitized = _INVALID_TOOLNAME_CHARS_REGEXP.sub('', input_str)

    # Step 2: Truncate to max 64 characters
    sanitized = sanitized[:64]

    return sanitized


def sanitize_filename(filename: str, replacement: str = "-") -> str:
    # Replace invalid characters with the replacement character
    sanitized = re.sub(r'[\\/:*?"<>|\s]', replacement, filename)
    return sanitized


def generate_attachment_filename(mime_type: Optional[str], base_filename: str = "quick-app"):
    extension = mimetypes.guess_extension(mime_type) if mime_type is not None else ""
    timestamp = datetime.now().isoformat(timespec='microseconds')
    filename = f"{base_filename}-{timestamp}{extension if extension is not None else ''}"
    return sanitize_filename(filename)


if __name__ == '__main__':
    mime_type = "vnd.psn.employees/json"
    allowed_mime_types = ["image/png", "image/jpeg", "vnd.psn.employees/json"]
    print(matches_type(mime_type, allowed_mime_types))
