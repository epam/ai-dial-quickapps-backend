import os

from aidial_sdk.chat_completion import Attachment

from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_core_client import DialCoreClient
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
        timeout: float | None = None,
    ) -> str:
        """Get attachment URL, handling local development case"""
        if settings.api_key:
            async with DialCoreClient(
                api_key=dial_api_key, base_url=dial_url, timeout=timeout
            ) as dial_core:
                file = await dial_core.get_file(attachment_url)
            async with DialCoreClient(settings.api_key, settings.url, timeout=timeout) as dial_core:
                bucket_info = await dial_core.put_file(
                    name=os.path.basename(attachment_url),
                    mime_type=attachment.type,
                    content=file,
                )
                return bucket_info['url']

        return attachment_url
