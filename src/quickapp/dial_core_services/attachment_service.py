import base64
import logging

from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Attachment
from injector import inject

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
            f"Uploading attachment: {attachment.title}, url: {attachment.url}, data present: {attachment.data is not None}"
        )
        if attachment.url is None and attachment.data:
            try:
                attachment_name = attachment.title or generate_attachment_filename(attachment.type)
                bucket_resp = await self.__dial_client.bucket.get_raw()
                bucket = bucket_resp.appdata or bucket_resp.bucket
                metadata = await self.__dial_client.files.upload(
                    url=f"files/{bucket}/{attachment_name}",
                    file=(attachment_name, _get_bytes(attachment.data), attachment.type),
                )
                # Use URL instead of data for uploaded attachment.
                attachment.data = None
                attachment.url = metadata.url
                logger.debug(f"Uploaded attachment {attachment_name} to {attachment.url}")
            except Exception:
                logger.exception(
                    "Exception during uploading attachment to DIAL. Original attachment left in place."
                )
        return attachment
