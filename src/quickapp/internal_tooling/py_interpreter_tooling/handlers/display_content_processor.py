import base64
import json
import logging
from typing import Any

from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.media_types import MediaTypes
from quickapp.common.utils import generate_attachment_filename
from quickapp.internal_tooling.py_interpreter_tooling._constants import (
    SUPPORTED_DISPLAY_MEDIA_TYPES,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.response import CodeExecutionResponse

_NAMING_SYS_PROMPT = (
    "Generate a short, descriptive title based on the content provided.\n"
    "Title should have from 1 up to 7 words!\n"
    "Example: `Python function calculating Fibonacci sequence...` -> `Fibonacci calculator`"
)

logger = logging.getLogger(__name__)


@inject
class DisplayContentProcessor:
    """Handles processing and sanitization of display content"""

    def __init__(self, dial_client: AsyncDial):
        self.__dial_client: AsyncDial = dial_client

    async def process_display_content(
        self,
        display_content: list[dict[str, Any]],
        display_title: str | None = None,
    ) -> list[Attachment]:
        """Processes display content and creates necessary attachments"""
        attachments: list[Attachment] = []
        for content_dict in display_content:
            attachments.extend(await self._display_item_to_attachments(content_dict))

        for i, att in enumerate(attachments):
            if display_title:
                att.title = display_title if len(attachments) == 1 else f"{display_title} ({i + 1})"

        return attachments

    async def _display_item_to_attachments(self, content_dict: dict[str, Any]) -> list[Attachment]:
        """Processes a single display item and creates an attachment if needed"""
        attachments: list[Attachment] = []

        for media_type, data in content_dict.items():
            if media_type in SUPPORTED_DISPLAY_MEDIA_TYPES:
                bucket_url = await self._publish_to_bucket(media_type, data)

                if media_type and bucket_url:
                    attachment = Attachment(type=media_type, url=bucket_url)
                    attachments.append(attachment)

        return attachments

    async def _publish_to_bucket(self, mime_type: str, data: str | dict[str, Any]) -> str:
        filename = generate_attachment_filename(mime_type)
        bucket_resp = await self.__dial_client.bucket.get_raw()
        bucket = bucket_resp.appdata or bucket_resp.bucket
        metadata = await self.__dial_client.files.upload(
            url=f"files/{bucket}/{filename}",
            file=(filename, self._prepare_content(mime_type, data), mime_type),
        )
        return metadata.url

    @staticmethod
    def _prepare_content(mime_type: str, data: str | dict[str, Any]) -> bytes:
        """Prepares content for storage based on mime type"""
        if mime_type in (MediaTypes.PNG, MediaTypes.JPEG, MediaTypes.GIF):
            if isinstance(data, dict):
                raise ValueError("Binary content (images) must be provided as string, not dict")
            return base64.b64decode(data)

        if isinstance(data, dict):
            return json.dumps(data).encode("utf-8")

        return data.encode("utf-8")

    @staticmethod
    def sanitize_display_content(execution_result: CodeExecutionResponse) -> CodeExecutionResponse:
        """Sanitizes display content in the execution result"""
        if execution_result.display:
            for info_dict in execution_result.display:
                for media_type in info_dict:
                    if media_type not in (MediaTypes.PLAIN_TEXT, MediaTypes.MARKDOWN):
                        info_dict[media_type] = "Content will be presented as attachment"

        return execution_result
