import os
from io import BytesIO

import openai
from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Attachment

from quickapp.common import DIAL_API_KEY
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PyInterpreterSettings,
)


class InputFileHandler:
    """Handles file operations for the PyCodeInterpreterTool"""

    async def get_attachment_url(
        self,
        settings: _PyInterpreterSettings,
        dial_api_key: DIAL_API_KEY,
        attachment_url: str,
        attachment: Attachment,
        dial_url: str,
        timeout: float,
    ) -> str:
        """Get attachment URL, handling local development case"""
        if settings.api_key:
            client_timeout = openai.Timeout(connect=5, read=timeout, write=timeout, pool=timeout)
            request_dial = AsyncDial(
                api_key=dial_api_key.get_secret_value(),
                base_url=dial_url,
                timeout=client_timeout,
            )
            file_content = await (await request_dial.files.download(attachment_url)).aget_content()

            dev_dial = AsyncDial(
                api_key=settings.api_key.get_secret_value(),
                base_url=settings.url,
                timeout=client_timeout,
            )
            bucket_resp = await dev_dial.bucket.get_raw()
            bucket = bucket_resp.appdata or bucket_resp.bucket
            filename = os.path.basename(attachment_url)
            metadata = await dev_dial.files.upload(
                f"files/{bucket}/{filename}",
                (filename, BytesIO(file_content), attachment.type),
            )
            return metadata.url

        return attachment_url
