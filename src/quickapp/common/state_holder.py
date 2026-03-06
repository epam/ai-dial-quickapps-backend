import logging
from hashlib import sha256
from typing import Any

from aidial_sdk.chat_completion import Attachment, ToolCall
from pydantic import BaseModel, Field, PrivateAttr

logger = logging.getLogger(__name__)


class StateHolder(BaseModel):
    attachments: list[Attachment] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    _state: dict[str, Any] = PrivateAttr(default_factory=dict)
    _file_data_dict: dict[str, bytes] = PrivateAttr(default_factory=dict)

    def add_state(self, key: str, value: Any) -> None:
        logger.debug(f"Added state [{key}]={value}")
        self._state[key] = value

    def get_state(self) -> dict[str, Any]:
        logger.debug(f"Read state {self._state}")
        return self._state

    def get_file_data(self, url: str | None = None, key: str | None = None) -> bytes | None:
        if not url and not key:
            raise RuntimeError("Either url or key should be defined.")
        if not key and url:
            key = self._get_file_key_by_url(url)
        if key:
            file_data = self._file_data_dict.get(key)
            if file_data:
                return file_data
        return None

    def store_file_data(self, url: str, file_data: bytes) -> None:
        key = self._get_file_key_by_url(url)
        self._file_data_dict[key] = file_data

    @staticmethod
    def _get_file_key_by_url(url: str) -> str:
        return sha256(url.encode('utf-8')).hexdigest()
