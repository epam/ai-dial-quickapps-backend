import base64
import logging

from aidial_client import AsyncDial
from aidial_client.types.metadata import FileMetadata
from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.url_sanitization import sanitize_url_for_log
from quickapp.common.utils import generate_attachment_filename

logger = logging.getLogger(__name__)


# move to utils?
def _get_bytes(data: str) -> bytes:
    try:
        decoded = base64.b64decode(data, validate=True)
        return decoded
    except Exception:
        return data.encode()


@inject
class AttachmentService:

    def __init__(self, dial_client: AsyncDial):
        self.__dial_client: AsyncDial = dial_client

    async def upload_attachment_to_core(self, attachment: Attachment) -> Attachment:
        logger.debug(
            "Uploading attachment: %s, url: %s, data present: %s",
            attachment.title,
            sanitize_url_for_log(attachment.url) if attachment.url else None,
            attachment.data is not None,
        )
        if attachment.url is None and attachment.data:
            try:
                attachment_name = attachment.title or generate_attachment_filename(attachment.type)
                metadata = await self.upload_bytes(
                    data=_get_bytes(attachment.data),
                    content_type=attachment.type,
                    filename=attachment_name,
                )
                # Use URL instead of data for uploaded attachment.
                attachment.data = None
                attachment.url = metadata.url
                logger.debug(
                    "Uploaded attachment %s to %s",
                    attachment_name,
                    sanitize_url_for_log(attachment.url),
                )
            except Exception:
                logger.exception(
                    "Exception during uploading attachment to DIAL. Original attachment left in place."
                )
        return attachment

    async def upload_bytes(
        self,
        data: bytes,
        content_type: str | None,
        filename: str,
    ) -> FileMetadata:
        bucket_resp = await self.__dial_client.bucket.get_raw()
        bucket = bucket_resp.appdata or bucket_resp.bucket
        return await self.__dial_client.files.upload(
            url=f"files/{bucket}/{filename}",
            file=(filename, data, content_type),
        )
