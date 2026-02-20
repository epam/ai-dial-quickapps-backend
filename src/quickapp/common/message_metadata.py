from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

MESSAGE_METADATA_KEY = "_message_metadata"
USER_TIMEZONE_STATE_KEY = "_user_timezone"


class TimestampSource(str, Enum):
    SERVER = "server"
    USER_TIMEZONE = "user_timezone"


class TimestampMetadata(BaseModel):
    response_timestamp: datetime | None = None
    timestamp_source: TimestampSource | None = None
    timezone_name: str | None = None
    skip_time_annotation: bool = False


class MessageMetadata(BaseModel):
    timestamp: TimestampMetadata | None = None
    content_type: str | None = None

    @staticmethod
    def from_state(state: dict[str, Any] | None) -> "MessageMetadata":
        if not state or MESSAGE_METADATA_KEY not in state:
            return MessageMetadata()
        return MessageMetadata.model_validate(state[MESSAGE_METADATA_KEY])

    def to_state_entry(self) -> dict[str, Any]:
        return {MESSAGE_METADATA_KEY: self.model_dump(exclude_none=True)}
