import base64
import json
import logging
import uuid
from io import BytesIO
from typing import Any

import plotly.io as pio
from aidial_client import AsyncDial
from aidial_client.types.chat.request_param import (
    AttachmentParam,
    CustomContentParam,
    Message,
    SystemMessageParam,
    UserMessageParam,
)
from aidial_client.types.chat.response import Attachment, ChatCompletionResponse
from injector import inject

from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_core_client import DialCoreClient
from quickapp.common.dial_settings import DialSettings
from quickapp.common.media_types import MediaTypes
from quickapp.common.utils import generate_attachment_filename
from quickapp.internal_tooling.py_interpreter_tooling._constants import (
    SUPPORTED_DISPLAY_MEDIA_TYPES,
)
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
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        dial_client: AsyncDial,
        py_interpreter_settings: _PyInterpreterSettings,
    ):
        self.__dial_settings: DialSettings = dial_settings
        self.__api_key: DIAL_API_KEY = api_key
        self.__dial_client: AsyncDial = dial_client
        self.__additional_handling_model: str = py_interpreter_settings.additional_handling_model
        pio.defaults.chromium_args = [
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
        ]

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
                attachment_dict = {"type": media_type}
                bucket_info = await self._publish_to_bucket(media_type, data)
                attachment_dict["url"] = bucket_info.get("url", "")

                if attachment_dict.get("type", None) and attachment_dict.get("url", None):
                    # generate by content file title
                    attachment_dict["data"] = json.dumps(data)
                    # TODO: need to verify this part when attachments will be ready
                    attachment = Attachment.model_validate(attachment_dict)
                    title = await self._generate_title(attachment)
                    # TODO: dirty fix, data and url shouldn't be both filled
                    attachment.data = None
                    attachment.title = title

                    attachments.append(attachment)

        return attachments

    async def _publish_to_bucket(self, mime_type: str, data: Any) -> dict[str, Any]:
        async with DialCoreClient(
            api_key=self.__api_key, base_url=self.__dial_settings.url
        ) as dial_core:
            filename = generate_attachment_filename(mime_type)

            return await dial_core.put_file(
                name=filename,
                mime_type=mime_type,
                content=self._prepare_content(mime_type, data),
            )

    def _prepare_content(self, mime_type: str, data: Any) -> bytes:
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

                return response.choices[0].message.content
            except Exception as e:
                logger.exception(f"Exception during generating title for attachment: {e}")

        return str(uuid.uuid4())

    async def _generate_attachment_message(self, attachment: Attachment) -> Message | None:
        message = None
        if attachment.type in (MediaTypes.CSV, MediaTypes.JSON, MediaTypes.XML):
            pass
            # TODO: later will be added the flow to download files from py interpreter and then we need to handle such case
        else:
            attachment_param = AttachmentParam(**attachment.model_dump())
            if attachment.type in (MediaTypes.PNG, MediaTypes.JPEG):
                message = UserMessageParam(
                    role='user',
                    custom_content=CustomContentParam(attachments=[attachment_param]),
                    content='',
                )
            elif attachment.type == MediaTypes.PLOTLY:
                message = UserMessageParam(
                    role='user',
                    custom_content=CustomContentParam(
                        attachments=[await self._get_plotly_as_img(attachment_param)]
                    ),
                    content='',
                )

        return message

    async def _get_plotly_as_img(self, attachment_param: AttachmentParam) -> AttachmentParam:
        fig = pio.from_json(attachment_param["data"])
        image_bytes = BytesIO()
        fig.write_image(image_bytes, format="png")
        image_bytes.seek(0)

        async with DialCoreClient(
            api_key=self.__api_key, base_url=self.__dial_settings.url
        ) as dial_core:
            filename = generate_attachment_filename(MediaTypes.PNG)
            bucket_info = await dial_core.put_file(
                name=filename,
                mime_type=MediaTypes.PNG,
                content=image_bytes,
            )

            return AttachmentParam(url=bucket_info.get("url"), type=MediaTypes.PNG)

    def sanitize_display_content(
        self, execution_result: CodeExecutionResponse
    ) -> CodeExecutionResponse:
        """Sanitizes display content in the execution result"""
        if execution_result.display:
            for info_dict in execution_result.display:
                for media_type, data in info_dict.items():
                    if media_type not in (MediaTypes.PLAIN_TEXT, MediaTypes.MARKDOWN):
                        info_dict[media_type] = "Content will be presented as attachment"

        return execution_result
