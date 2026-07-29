import logging
from hashlib import sha256
from typing import Any

from aidial_client.types.metadata import FileMetadata
from aidial_sdk.chat_completion import Attachment, ToolCall
from pydantic import BaseModel, Field, PrivateAttr

from quickapp.common.payload_logging import log_payload

logger = logging.getLogger(__name__)


class StateHolder(BaseModel):
    attachments: list[Attachment] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    _state: dict[str, Any] = PrivateAttr(default_factory=dict)
    _file_data_dict: dict[str, bytes] = PrivateAttr(default_factory=dict)
    _file_metadata_dict: dict[str, FileMetadata] = PrivateAttr(default_factory=dict)
    _file_content_type_dict: dict[str, str] = PrivateAttr(default_factory=dict)

    def add_state(self, key: str, value: Any) -> None:
        logger.debug("Added state [%s] (type=%s)", key, type(value).__name__)
        log_payload(logger, "Added state [%s]=%s", key, value)
        self._state[key] = value

    def get_state(self) -> dict[str, Any]:
        logger.debug("Read state keys: %s", list(self._state))
        log_payload(logger, "Read state: %s", self._state)
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

    def store_file_data(
        self,
        url: str,
        file_data: bytes,
        metadata: FileMetadata | None = None,
        content_type: str | None = None,
    ) -> None:
        key = self._get_file_key_by_url(url)
        self._file_data_dict[key] = file_data
        if metadata is not None:
            self._file_metadata_dict[key] = metadata
        resolved_type = content_type
        if resolved_type is None and metadata is not None:
            resolved_type = getattr(metadata, "content_type", None)
        if resolved_type:
            self._file_content_type_dict[key] = resolved_type

    def get_file_metadata(self, url: str) -> FileMetadata | None:
        key = self._get_file_key_by_url(url)
        return self._file_metadata_dict.get(key)

    def get_content_type(self, url: str) -> str | None:
        key = self._get_file_key_by_url(url)
        return self._file_content_type_dict.get(key)

    def invalidate_file_data(self, url: str) -> None:
        key = self._get_file_key_by_url(url)
        self._file_data_dict.pop(key, None)
        self._file_metadata_dict.pop(key, None)
        self._file_content_type_dict.pop(key, None)

    @staticmethod
    def _get_file_key_by_url(url: str) -> str:
        return sha256(url.encode('utf-8')).hexdigest()
