import re
from enum import Enum
from functools import lru_cache
from urllib.parse import urlsplit

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.url_sanitization import sanitize_url_for_log


class UrlScheme(str, Enum):
    DIAL = "dial"
    EXTERNAL = "external"
    DIAL_APPDIR_RELATIVE = "dial_appdir_relative"
    UNSUPPORTED = "unsupported"


_DIAL_RELATIVE_PATH = re.compile(r"^/*files/", re.IGNORECASE)

# Characters the DIAL UI forbids in resource names (ui-kit NOT_ALLOWED_SYMBOLS,
# minus '/' which is the path separator); control chars are rejected separately.
_FORBIDDEN_REFERENCE_CHARS = frozenset(':;,={}%&\\"')
# DIAL UI resource-name limits, in UTF-8 bytes: per path segment and for the whole
# resource id. The whole-reference cap is conservative — the real 1024-byte cap
# applies to the full id including the files/{appdata}/... prefix unknown here.
_MAX_SEGMENT_BYTES = 255
_MAX_REFERENCE_BYTES = 1024


def _is_control_char(ch: str) -> bool:
    """C0 control chars (0x00-0x1F, includes tab/newline), per ui-kit NOT_ALLOWED_SPACES."""
    return ord(ch) < 0x20


def is_appdir_relative(path: str) -> bool:
    """Whether ``path`` is a well-formed agent-home-relative file/dir reference.

    Accepted forms: a file (``file.md``, ``dir1/file.md``, extension optional) or a
    dir with a trailing slash (``some_dir/``, ``dir_1/dir2/``). Segments must be
    non-empty, must not be ``.``/``..`` or end with a dot, must not contain
    DIAL-forbidden characters or control characters, and must respect the DIAL
    resource-name length limits. This is the canonical detection predicate — every
    consumer that needs to recognise the appdir-relative convention must use it (or
    :func:`classify_url`) so the grammar cannot drift between call sites.
    """
    if not path:
        return False
    if len(path.encode("utf-8")) > _MAX_REFERENCE_BYTES:
        return False
    if any(ch in _FORBIDDEN_REFERENCE_CHARS or _is_control_char(ch) for ch in path):
        return False
    segments = path.split("/")
    if segments[-1] == "":
        segments = segments[:-1]  # dir form: a single trailing '/'
    if not segments:
        return False
    for segment in segments:
        if segment in ("", ".", "..") or segment.endswith("."):
            return False
        if len(segment.encode("utf-8")) > _MAX_SEGMENT_BYTES:
            return False
    return True


@lru_cache(maxsize=8)
def _dial_host(dial_base_url: str) -> str:
    try:
        return (urlsplit(dial_base_url).hostname or "").lower()
    except ValueError:
        return ""


def classify_url(url: str, dial_base_url: str) -> UrlScheme:
    """Classify a file reference URL against the configured DIAL base URL.

    A bare DIAL relative path (e.g. ``files/bucket/foo.pdf``) or an absolute URL
    whose host matches the configured DIAL host is :attr:`UrlScheme.DIAL`. Any
    other ``http(s)://`` URL is :attr:`UrlScheme.EXTERNAL`. A schemeless path
    matching :func:`is_appdir_relative` (e.g. ``reports/img.png``, ``some_dir/``)
    is :attr:`UrlScheme.DIAL_APPDIR_RELATIVE` — the agent-home-relative convention
    spoken by the file tools; how (and whether) to resolve it is the caller's
    decision. Anything else (``file:``, ``ftp:``, ``data:``, malformed, empty
    hostname) is :attr:`UrlScheme.UNSUPPORTED`.
    """
    if not url:
        return UrlScheme.UNSUPPORTED

    if _DIAL_RELATIVE_PATH.match(url):
        return UrlScheme.DIAL

    try:
        split = urlsplit(url)
    except ValueError:
        return UrlScheme.UNSUPPORTED

    scheme = (split.scheme or "").lower()
    if not scheme:
        if is_appdir_relative(url):
            return UrlScheme.DIAL_APPDIR_RELATIVE
        return UrlScheme.UNSUPPORTED
    if scheme not in ("http", "https"):
        return UrlScheme.UNSUPPORTED

    host = (split.hostname or "").lower()
    if not host:
        return UrlScheme.UNSUPPORTED

    dial_host = _dial_host(dial_base_url)
    if dial_host and host == dial_host:
        return UrlScheme.DIAL

    return UrlScheme.EXTERNAL


def unsupported_scheme_error(url: str, parameter_name: str) -> InvalidToolCallParameterException:
    """Build the canonical "URL scheme not supported" exception.

    Centralised so every consumer of :func:`classify_url` raises the same
    message; agents see consistent retry guidance regardless of where the
    rejection happens.
    """
    return InvalidToolCallParameterException(
        parameter_name=parameter_name,
        message=(
            f"URL scheme not supported: {sanitize_url_for_log(url)}. "
            "Only DIAL file paths (e.g. files/bucket/foo.pdf) and "
            "http(s) URLs are accepted."
        ),
    )
