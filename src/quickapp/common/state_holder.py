import logging
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, List, Optional

from aidial_sdk.chat_completion import Attachment, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class StateHolder:
    content: str = field(default="")
    attachments: List[Attachment] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    __state: dict[str, Any] = field(default_factory=dict)
    __file_contents: dict[str, str] = field(default_factory=dict)

    def add_state(self, key: str, value: Any) -> None:
        logger.debug(f"Added state [{key}]={value}")
        self.__state[key] = value

    def get_state(self) -> dict[str, Any]:
        logger.debug(f"Read state {self.__state}")
        return self.__state

    def get_file_content(
        self, url: Optional[str] = None, key: Optional[str] = None
    ) -> Optional[str]:
        if not url and not key:
            raise RuntimeError("Either url or key should be defined.")
        if not key and url:
            key = self.__get_file_key_by_url(url)
        if key:
            content = self.__file_contents.get(key)
            if content:
                return content
        return None

    def store_file_content(self, url: str, content: str) -> None:
        key = self.__get_file_key_by_url(url)
        self.__file_contents[key] = content

    @staticmethod
    def __get_file_key_by_url(url: str) -> str:
        return sha256(url.encode('utf-8')).hexdigest()
