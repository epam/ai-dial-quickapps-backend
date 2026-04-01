from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

MESSAGE_METADATA_KEY = "_message_metadata"


class TimestampSource(StrEnum):
    DEFAULT = "default"
    REQUEST = "request"


class TimestampMetadata(BaseModel):
    response_timestamp: datetime | None = None
    timestamp_source: TimestampSource | None = None
    timezone_name: str | None = None


class MessageMetadata(BaseModel):
    timestamp: TimestampMetadata | None = None


def get_metadata_from_state(state: dict[str, Any] | None) -> MessageMetadata | None:
    """Read MessageMetadata from a message/result state dict."""
    if not state:
        return None
    raw = state.get(MESSAGE_METADATA_KEY)
    if raw is None:
        return None
    return MessageMetadata.model_validate(raw)


def set_metadata_in_state(state: dict[str, Any], metadata: MessageMetadata) -> None:
    """Write MessageMetadata into a message/result state dict."""
    state[MESSAGE_METADATA_KEY] = metadata.model_dump(mode="json")
