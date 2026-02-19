from datetime import datetime
from typing import Any

from pydantic import BaseModel

MESSAGE_METADATA_KEY = "_message_metadata"


class MessageMetadata(BaseModel):
    response_timestamp: datetime | None = None

    @staticmethod
    def from_state(state: dict[str, Any] | None) -> "MessageMetadata":
        if not state or MESSAGE_METADATA_KEY not in state:
            return MessageMetadata()
        return MessageMetadata.model_validate(state[MESSAGE_METADATA_KEY])

    def to_state_entry(self) -> dict[str, Any]:
        return {MESSAGE_METADATA_KEY: self.model_dump(exclude_none=True)}
