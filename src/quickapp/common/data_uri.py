"""RFC 2397 ``data:`` URI parsing, detection, and log collapsing.

A ``data:`` URI carries its whole payload inline, so it is the one URL shape that must
never be logged or echoed back to the model verbatim (issue #436's content rule, and the
context-window overflow that motivated this module). Detection is deliberately kept out of
:func:`quickapp.common.url_classification.classify_url`: most dispatch sites must keep
rejecting inline content, so a caller that wants to accept it opts in explicitly.

Stdlib-only by design — :mod:`quickapp.common.url_sanitization` imports from here.
"""

import base64
import binascii
import re
from urllib.parse import unquote_to_bytes

from pydantic import BaseModel, ConfigDict

_DATA_URI_PREFIX = re.compile(r"^data:", re.IGNORECASE)

# RFC 2397: an absent media type means text/plain;charset=US-ASCII. Only the base type is
# kept — it is what feeds extension guessing and the outbound Content-Type.
_DEFAULT_MEDIA_TYPE = "text/plain"

# Media types are short; anything longer is malformed or an attempt to smuggle payload into
# the one part of the URI that is safe to log.
_MAX_LOGGED_MEDIA_TYPE_CHARS = 100


class DataUri(BaseModel):
    """The decoded contents of a ``data:`` URI."""

    model_config = ConfigDict(frozen=True)

    media_type: str
    data: bytes


def is_data_uri(value: str) -> bool:
    """Whether ``value`` is a ``data:`` URI. Cheap prefix test — does not validate the body."""
    return bool(value) and _DATA_URI_PREFIX.match(value) is not None


def parse_data_uri(value: str) -> DataUri:
    """Decode a ``data:`` URI into its media type and bytes.

    Raises :class:`ValueError` if the URI is malformed (no comma separator, or a payload
    that is neither valid base64 nor valid percent-encoding). The message never includes
    the payload.
    """
    if not is_data_uri(value):
        raise ValueError("Not a data: URI")

    body = value[len("data:") :]
    metadata, separator, payload = body.partition(",")
    if not separator:
        raise ValueError("Malformed data: URI - missing the ',' payload separator")

    parts = metadata.split(";")
    is_base64 = bool(parts) and parts[-1].strip().lower() == "base64"
    if is_base64:
        parts = parts[:-1]
    media_type = parts[0].strip().lower() if parts and parts[0].strip() else _DEFAULT_MEDIA_TYPE

    if is_base64:
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "Malformed data: URI - the base64 payload could not be decoded"
            ) from exc
    else:
        try:
            data = unquote_to_bytes(payload)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(
                "Malformed data: URI - the percent-encoded payload could not be decoded"
            ) from exc

    return DataUri(media_type=media_type, data=data)


def collapse_data_uri_for_log(value: str) -> str:
    """Replace a ``data:`` URI's inline payload with its size.

    ``data:application/pdf;base64,JVBERi0...`` becomes
    ``data:application/pdf;base64,<elided 2411904 chars>``. The metadata prefix is kept
    because it is useful for diagnosis and cannot carry a payload once truncated.
    """
    body = value[len("data:") :] if is_data_uri(value) else value
    metadata, separator, payload = body.partition(",")
    if not separator:
        # No payload separator: the whole thing is metadata, but it may still be huge.
        metadata, payload = body, ""
    if len(metadata) > _MAX_LOGGED_MEDIA_TYPE_CHARS:
        metadata = f"{metadata[:_MAX_LOGGED_MEDIA_TYPE_CHARS]}..."
    return f"data:{metadata},<elided {len(payload)} chars>"
