import logging
import mimetypes
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from quickapp.config.tools.const import ALL_MIME_TYPES

logger = logging.getLogger(__name__)


_INVALID_TOOLNAME_CHARS_REGEXP: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9_-]+")
_INVALID_TOOLNAME_LEADING_CHAR_REGEXP: re.Pattern[str] = re.compile(r"^[^a-zA-Z_]")


# Normalize propagation types (split wildcards like 'image/*' for matching)
def matches_type(mime_type: str | None, allowed_mime_types: list[str] | None) -> bool:
    if mime_type is None:
        logger.warning(
            f"The mime_type is None, for the match check. Allowed_mime_types: {allowed_mime_types}"
        )
        return False
    if allowed_mime_types is None:
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


def fenced_code_block(text: str, language: str = "") -> str:
    """Wrap ``text`` in a Markdown fenced code block that survives nested fences.

    Per CommonMark, a fenced block is closed by a line with at least as many
    backticks as its opening fence. Content that itself contains ``` runs (a skill
    body, a markdown file) would otherwise break out of a fixed triple-backtick
    fence and corrupt the rendered stage. Open with a fence one backtick longer
    than the longest backtick run in ``text`` (minimum three).
    """
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def posix_path_last_segment(path: str) -> str:
    """Return the final segment of a POSIX-style path (``/`` separators only).

    For DIAL ``files/...`` URLs and similar strings; uses :class:`pathlib.PurePosixPath`
    instead of :func:`os.path.basename` so behavior does not depend on OS path rules.
    Trailing slashes are normalized away by ``pathlib`` (e.g. ``files/bucket/`` →
    segment ``bucket``). If ``.name`` is empty, returns the stripped path as a fallback.
    """
    stripped = path.strip()
    name = PurePosixPath(stripped).name
    return name if name else stripped


def substitute_media_type(
    mime_type: str | None,
    mapping: dict[str, str],
) -> str | None:
    """Apply media type substitution"""
    if mime_type is None:
        return None
    return mapping.get(mime_type, mime_type)


def sanitize_toolname(input_str: str) -> str:
    """
    Sanitizes a non-empty string to match the pattern ^[a-zA-Z_][a-zA-Z0-9_-]{0,63}$

    Invalid characters are replaced with '_'; a leading character that isn't
    a letter or underscore (a digit or '-') is itself prefixed with '_'
    (some providers, e.g. Gemini, reject function names that don't start
    with a letter or underscore, even though OpenAI and Anthropic allow it);
    the result is truncated to 64 characters.
    """
    sanitized = _INVALID_TOOLNAME_CHARS_REGEXP.sub('_', input_str)
    if _INVALID_TOOLNAME_LEADING_CHAR_REGEXP.match(sanitized):
        sanitized = f"_{sanitized}"
    sanitized = sanitized[:64]
    return sanitized


def sanitize_filename(filename: str, replacement: str = "-") -> str:
    # Replace invalid characters with the replacement character
    sanitized = re.sub(r'[\\/:*?"<>|\s]', replacement, filename)
    return sanitized


# Office MIME types that ``mimetypes.guess_extension`` misses when the OS has no
# ``/etc/mime.types`` (python:*-alpine / python:*-slim). Covered by the Alpine
# ``mailcap`` package in Docker; this map keeps behaviour correct without it.
_MIME_TYPE_TO_EXTENSION_FALLBACK: dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
}


def guess_attachment_extension(mime_type: str | None) -> str:
    """Return a filename extension for ``mime_type``, or ``""`` if unknown.

    Strips Content-Type parameters (e.g. ``; charset=utf-8``) before lookup.
    Falls back to a small Office MIME map when the stdlib mime DB has no entry
    (common on Alpine/slim images without ``/etc/mime.types``).
    """
    if mime_type is None:
        return ""
    base_type = mime_type.split(";", 1)[0].strip()
    if not base_type:
        return ""
    extension = mimetypes.guess_extension(base_type)
    if not extension:
        extension = _MIME_TYPE_TO_EXTENSION_FALLBACK.get(base_type, "")
    return extension or ""


def generate_attachment_filename(mime_type: str | None, base_filename: str = "quick-app"):
    extension = guess_attachment_extension(mime_type)
    timestamp = datetime.now().isoformat(timespec='microseconds')
    filename = f"{base_filename}-{timestamp}{extension}"
    return sanitize_filename(filename)


def filename_from_url_path(url: str) -> str | None:
    """Return the URL-decoded last path segment of ``url``, or ``None`` if absent."""
    try:
        path = urlsplit(url).path
    except ValueError:
        return None
    if not path:
        return None
    last = path.rstrip("/").rsplit("/", 1)[-1]
    if not last:
        return None
    return unquote(last) or None


def to_plain_dict(obj: Any, _seen: set[int] | None = None) -> Any:
    """
    Recursively convert an object into plain JSON-serializable structures.

    Behavior:
    - Preserves JSON primitives (str, int, float, bool) as-is.
    - Returns an empty dict for top-level None (backwards-compatible).
    - Converts Pydantic v2 models using `model_dump(exclude_none=True)`,
      then recurses.
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
