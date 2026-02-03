import logging
import mimetypes
import re
from datetime import datetime
from typing import Optional, Any

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

def to_plain_dict(obj: Any) -> dict:
    """
    Convert an object into a plain dict.

    Behavior:
    - Returns an empty dict for None.
    - If the object exposes a `.dict()` method (e.g. pydantic models), returns
      obj.dict(exclude_none=True) to avoid including None values; falls back to
      obj.dict() if exclude_none is not supported.
    - If the object is already a dict, returns a copy with None-valued entries
      removed.
    - Otherwise, attempts to coerce the object to a dict via dict(obj).
    - On any error, returns an empty dict.

    This helper was moved into quickapp.common.utils to provide a shared,
    defensive conversion used across the codebase (pydantic models, mapping-like
    objects, and iterable-of-pairs).

    Args:
        obj: Any serializable/mapping-like object to convert.

    Returns:
        A plain dict representation (never None).

    Example:
        >>> to_plain_dict(None)
        {}
        >>> to_plain_dict({"a": 1, "b": None})
        {"a": 1}
    """

    if obj is None:
        return {}
    if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
        try:
            return obj.dict(exclude_none=True)
        except Exception:
            try:
                return obj.dict()
            except Exception:
                return {}
    if isinstance(obj, dict):
        # drop None values for cleanliness
        return {k: v for k, v in obj.items() if v is not None}
    try:
        return dict(obj)
    except Exception:
        return {}



if __name__ == '__main__':
    mime_type = "vnd.psn.employees/json"
    allowed_mime_types = ["image/png", "image/jpeg", "vnd.psn.employees/json"]
    print(matches_type(mime_type, allowed_mime_types))
