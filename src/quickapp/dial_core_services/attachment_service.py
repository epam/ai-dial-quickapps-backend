import base64
import logging
from io import BytesIO

from injector import inject

from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_core_client import Attachment, DialCoreClient
from quickapp.common.dial_settings import DialSettings
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

    def __init__(self, dial_settings: DialSettings, api_key: DIAL_API_KEY):
        self.__dial_settings: DialSettings = dial_settings
        self.__api_key: DIAL_API_KEY = api_key

    async def upload_attachment_to_core(self, attachment: Attachment) -> Attachment:
        logger.debug(
            f"Uploading attachment: {attachment.title}, url: {attachment.url}, data present: {attachment.data is not None}"
        )
        if attachment.url is None and attachment.data:
            try:
                async with DialCoreClient(
                    base_url=self.__dial_settings.url, api_key=self.__api_key
                ) as dial_core:
                    attachment_name = attachment.title or generate_attachment_filename(
                        attachment.type
                    )
                    metadata = await dial_core.put_file(
                        name=attachment_name,
                        mime_type=attachment.type,
                        content=BytesIO(_get_bytes(attachment.data)),
                    )
                    # Use URL instead of data for uploaded attachment.
                    attachment.data = None
                    attachment.url = metadata.get("url")
                    logger.debug(f"Uploaded attachment {attachment_name} to {attachment.url}")
            except Exception:
                logger.exception(
                    "Exception during uploading attachment to DIAL. Original attachment left in place."
                )
        return attachment
