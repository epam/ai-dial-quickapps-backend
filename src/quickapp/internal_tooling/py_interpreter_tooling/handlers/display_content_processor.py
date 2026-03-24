import base64
import json
import logging
import uuid
from typing import Any

from aidial_client import AsyncDial
from aidial_client.types.chat.request_param import (
    AttachmentParam,
    CustomContentParam,
    Message,
    SystemMessageParam,
    UserMessageParam,
)
from aidial_client.types.chat.response import ChatCompletionResponse
from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.media_types import MediaTypes
from quickapp.common.utils import generate_attachment_filename
from quickapp.internal_tooling.py_interpreter_tooling._constants import (
    SUPPORTED_DISPLAY_MEDIA_TYPES,
)
from quickapp.internal_tooling.py_interpreter_tooling._kaleido_service import _KaleidoService
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PyInterpreterSettings,
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

    def __init__(
        self,
        dial_client: AsyncDial,
        py_interpreter_settings: _PyInterpreterSettings,
        kaleido_service: _KaleidoService,
    ):
        self.__dial_client: AsyncDial = dial_client
        self.__additional_handling_model: str = py_interpreter_settings.additional_handling_model
        self.__kaleido_service: _KaleidoService = kaleido_service

    async def process_display_content(
        self,
        display_content: list[dict[str, Any]],
    ) -> list[Attachment]:
        """Processes display content and creates necessary attachments"""
        result = []
        for content_dict in display_content:
            attachments: list[Attachment] = await self._display_item_to_attachments(content_dict)
            result.extend(attachments)
        return result

    async def _display_item_to_attachments(self, content_dict: dict[str, Any]) -> list[Attachment]:
        """Processes a single display item and creates an attachment if needed"""
        attachments: list[Attachment] = []

        for media_type, data in content_dict.items():
            if media_type in SUPPORTED_DISPLAY_MEDIA_TYPES:
                bucket_url = await self._publish_to_bucket(media_type, data)

                if media_type and bucket_url:
                    # Create a temporary data-only attachment for title generation
                    temp_attachment = Attachment(type=media_type, data=json.dumps(data))
                    title = await self._generate_title(temp_attachment)
                    # Create the final url-only attachment
                    attachment = Attachment(type=media_type, url=bucket_url, title=title)

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

    async def _generate_title(self, attachment: Attachment) -> str:
        user_message = await self._generate_attachment_message(attachment)
        if user_message:
            messages = [
                SystemMessageParam(role='system', content=_NAMING_SYS_PROMPT),
                user_message,
            ]
            try:
                response: ChatCompletionResponse = await self.__dial_client.chat.completions.create(
                    deployment_name=self.__additional_handling_model,
                    stream=False,
                    messages=messages,
                )

                # TODO: need to add usage statistics

                return response.choices[0].message.content or str(uuid.uuid4())
            except Exception as e:
                logger.exception(f"Exception during generating title for attachment: {e}")

        return str(uuid.uuid4())

    async def _generate_attachment_message(self, attachment: Attachment) -> Message | None:
        message = None
        if attachment.type in (MediaTypes.CSV, MediaTypes.JSON, MediaTypes.XML):
            pass
            # TODO: later will be added the flow to download files from py interpreter and then we need to handle such case
        else:
            attachment_param = AttachmentParam(**attachment.model_dump())  # type: ignore[typeddict-item]
            if attachment.type in (MediaTypes.PNG, MediaTypes.JPEG):
                message = UserMessageParam(
                    role='user',
                    custom_content=CustomContentParam(attachments=[attachment_param]),
                    content='',
                )
            elif attachment.type == MediaTypes.PLOTLY:
                plotly_image = await self._get_plotly_as_img(attachment_param)
                message = UserMessageParam(
                    role='user',
                    custom_content=CustomContentParam(
                        attachments=[plotly_image] if plotly_image else None
                    ),
                    content='',
                )

        return message

    async def _get_plotly_as_img(self, attachment_param: AttachmentParam) -> AttachmentParam | None:
        image_data = await self.__kaleido_service.render_figure_as_png(attachment_param["data"])

        filename = generate_attachment_filename(MediaTypes.PNG)
        bucket_resp = await self.__dial_client.bucket.get_raw()
        bucket = bucket_resp.appdata or bucket_resp.bucket
        try:
            metadata = await self.__dial_client.files.upload(
                url=f"files/{bucket}/{filename}",
                file=(filename, image_data, MediaTypes.PNG),
            )

            return AttachmentParam(url=metadata.url, type=MediaTypes.PNG)
        except Exception as e:
            logger.exception(f"Exception during uploading plotly image to DIAL: {e}")
        return None

    @staticmethod
    def sanitize_display_content(execution_result: CodeExecutionResponse) -> CodeExecutionResponse:
        """Sanitizes display content in the execution result"""
        if execution_result.display:
            for info_dict in execution_result.display:
                for media_type, data in info_dict.items():
                    if media_type not in (MediaTypes.PLAIN_TEXT, MediaTypes.MARKDOWN):
                        info_dict[media_type] = "Content will be presented as attachment"

        return execution_result
