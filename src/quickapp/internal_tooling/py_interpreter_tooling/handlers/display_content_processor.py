import base64
import json
import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.media_types import MediaTypes
from quickapp.config.tools.base import AttachmentHandlingMode
from quickapp.dial_core_services.attachment_service import AttachmentService
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

    def __init__(self, attachment_service: AttachmentService):
        self.__attachment_service: AttachmentService = attachment_service

    async def process_display_content(
        self,
        display_content: list[dict[str, Any]],
        display_title: str | None = None,
        handling_mode: AttachmentHandlingMode = AttachmentHandlingMode.upload_to_core,
    ) -> list[Attachment]:
        """Processes display content and creates necessary attachments"""
        attachments: list[Attachment] = []
        for content_dict in display_content:
            attachments.extend(
                await self._display_item_to_attachments(content_dict, handling_mode=handling_mode)
            )

        for i, att in enumerate(attachments):
            if display_title:
                att.title = display_title if len(attachments) == 1 else f"{display_title} ({i + 1})"

        return attachments

    async def _display_item_to_attachments(
        self,
        content_dict: dict[str, Any],
        handling_mode: AttachmentHandlingMode,
    ) -> list[Attachment]:
        """Processes a single display item and creates an attachment if needed"""
        attachments: list[Attachment] = []

        for media_type, data in content_dict.items():
            if media_type in SUPPORTED_DISPLAY_MEDIA_TYPES:
                attachment = Attachment(
                    type=media_type,
                    data=self._prepare_content(media_type, data),
                )
                attachment = await self.__attachment_service.handle_attachment(
                    attachment,
                    handling_mode,
                )
                attachments.append(attachment)

        return attachments

    @staticmethod
    def _prepare_content(mime_type: str, data: str | dict[str, Any]) -> str:
        """Prepares content for storage based on mime type"""
        if mime_type in (MediaTypes.PNG, MediaTypes.JPEG, MediaTypes.GIF):
            if isinstance(data, dict):
                raise ValueError("Binary content (images) must be provided as string, not dict")
            base64.b64decode(data)
            return data

        if isinstance(data, dict):
            return json.dumps(data)

        return data

    @staticmethod
    def sanitize_display_content(execution_result: CodeExecutionResponse) -> CodeExecutionResponse:
        """Sanitizes display content in the execution result"""
        if execution_result.display:
            for info_dict in execution_result.display:
                for media_type in info_dict:
                    if media_type not in (MediaTypes.PLAIN_TEXT, MediaTypes.MARKDOWN):
                        info_dict[media_type] = "Content will be presented as attachment"

        return execution_result
