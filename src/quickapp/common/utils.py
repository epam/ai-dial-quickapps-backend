import logging
import mimetypes
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

ALL_MIME_TYPES = "*/*"


# Normalize propagation types (split wildcards like 'image/*' for matching)
def matches_type(mime_type: str, allowed_mime_types: list[str]) -> bool:
    if mime_type is None:
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


def sanitize_filename(filename: str, replacement: str = "-") -> str:
    # Replace invalid characters with the replacement character
    sanitized = re.sub(r'[\\/:*?"<>|\s]', replacement, filename)
    return sanitized


def generate_attachment_filename(mime_type: Optional[str], base_filename: str = "quick-app"):
    extension = mimetypes.guess_extension(mime_type) if mime_type is not None else ""
    timestamp = datetime.now().isoformat(timespec='microseconds')
    filename = f"{base_filename}-{timestamp}{extension if extension is not None else ''}"
    return sanitize_filename(filename)
