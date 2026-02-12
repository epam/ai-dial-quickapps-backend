import logging
import mimetypes
import re
from datetime import datetime
from typing import Any, Optional

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


def to_plain_dict(obj: Any, _seen: set[int] | None = None) -> Any:
    """
    Recursively convert an object into plain JSON-serializable structures.

    Behavior:
    - Preserves JSON primitives (str, int, float, bool) as-is.
    - Returns an empty dict for top-level None (backwards-compatible).
    - Converts Pydantic v2 (`model_dump`) or v1 (`dict`) using `exclude_none=True`
      when available, then recurses.
    - Recursively converts dicts, lists, tuples, sets and mapping-like objects,
      dropping entries with None or empty dict values.
    - Attempts `dict(obj)` for iterable-of-pairs fallback.
    - Avoids infinite recursion using `_seen`.
    - On failure returns an empty dict.
    """
    if _seen is None:
        _seen = set()

    try:
        obj_id = id(obj)
    except Exception:
        obj_id = None

    if obj_id is not None:
        if obj_id in _seen:
            return {}
        _seen.add(obj_id)

    # None -> empty dict (preserve previous top-level behavior)
    if obj is None:
        return {}

    # Primitive JSON types are returned unchanged
    if isinstance(obj, (str, int, float, bool)):
        return obj

    # Pydantic v2
    if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
        try:
            dumped = obj.model_dump(exclude_none=True)
        except Exception:
            try:
                dumped = obj.model_dump()
            except Exception:
                return {}
        return to_plain_dict(dumped, _seen)

    # Pydantic v1 or similar .dict() API
    if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
        try:
            dumped = obj.dict(exclude_none=True)
        except Exception:
            try:
                dumped = obj.dict()
            except Exception:
                return {}
        return to_plain_dict(dumped, _seen)

    # Mapping / dict -> recurse and drop None/empty values
    if isinstance(obj, dict):
        result: dict = {}
        for k, v in obj.items():
            normalized = to_plain_dict(v, _seen)
            if normalized is None or normalized == {}:
                continue
            result[k] = normalized
        return result

    # Iterable containers -> normalize elements and return list (drop empty/None)
    if isinstance(obj, (list, tuple, set)):
        normalized_list = []
        for item in obj:
            n = to_plain_dict(item, _seen)
            if n is None or n == {}:
                continue
            normalized_list.append(n)
        return normalized_list

    # Try to coerce mapping-like via dict() and recurse
    try:
        coerced = dict(obj)
        return to_plain_dict(coerced, _seen)
    except Exception:
        pass

    # As a last resort, return the object if JSON-serializable, else empty dict
    try:
        import json

        json.dumps(obj)
        return obj
    except Exception:
        return {}
