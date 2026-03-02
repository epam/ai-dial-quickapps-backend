import logging
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from aidial_sdk.chat_completion import Attachment, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class StateHolder:
    attachments: list[Attachment] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    __state: dict[str, Any] = field(default_factory=dict)
    __file_data_dict: dict[str, bytes] = field(default_factory=dict)

    def add_state(self, key: str, value: Any) -> None:
        logger.debug(f"Added state [{key}]={value}")
        self.__state[key] = value

    def get_state(self) -> dict[str, Any]:
        logger.debug(f"Read state {self.__state}")
        return self.__state

    def get_file_data(
        self, url: str | None = None, key: str | None = None
    ) -> bytes | None:
        if not url and not key:
            raise RuntimeError("Either url or key should be defined.")
        if not key and url:
            key = self.__get_file_key_by_url(url)
        if key:
            file_data = self.__file_data_dict.get(key)
            if file_data:
                return file_data
        return None

    def store_file_data(self, url: str, file_data: bytes) -> None:
        key = self.__get_file_key_by_url(url)
        self.__file_data_dict[key] = file_data

    @staticmethod
    def __get_file_key_by_url(url: str) -> str:
        return sha256(url.encode('utf-8')).hexdigest()
