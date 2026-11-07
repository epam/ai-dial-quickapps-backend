import base64
import logging
from collections.abc import Awaitable, Callable

from aidial_client import AsyncDial
from aidial_client.types.metadata import FileItem
from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.project_context import PROJECT_CONTEXT
from quickapp.common.url_sanitization import sanitize_url
from quickapp.common.utils import generate_attachment_filename
from quickapp.dial_core_services.dial_file_service import DialFileService

logger = logging.getLogger(__name__)

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


# move to utils?
def _get_bytes(data: str) -> bytes:
    try:
        decoded = base64.b64decode(data, validate=True)
        return decoded
    except Exception:
        return data.encode()


@inject
class AttachmentService:
    """Uploads generated files to DIAL storage, flat under one of two roots.

    - **Output root** (``upload_output_*``): files produced for the user (MCP tool files,
      REST response files, interpreter charts). The current project's ``artifacts/`` in a
      project chat, so Chat lists them as the project's Outputs; the appdata root otherwise.
    - **Appdata root** (``upload_appdata_*``): internal files (large-result offloads,
      promoted external URLs). Always appdata, project or not.

    Both roots keep the same naming and overwrite behaviour: ``{root}{filename}``, written
    unconditionally, so a same-named file is replaced.
    """

    def __init__(
        self,
        dial_client: AsyncDial,
        file_service: DialFileService,
        project: PROJECT_CONTEXT,
    ):
        self.__dial_client: AsyncDial = dial_client
        self.__file_service: DialFileService = file_service
        self.__project: PROJECT_CONTEXT = project

    async def upload_output_attachment(self, attachment: Attachment) -> Attachment:
        """Upload the inline ``data`` of ``attachment`` to the output root (see the class doc).

        On failure the original attachment is returned unchanged.
        """
        return await self._upload_attachment(attachment, self.upload_output_bytes)

    async def upload_appdata_attachment(self, attachment: Attachment) -> Attachment:
        """Upload the inline ``data`` of ``attachment`` to the appdata root.

        On failure the original attachment is returned unchanged.
        """

        async def upload(data: bytes, content_type: str | None, filename: str) -> str:
            return (await self.upload_appdata_bytes(data, content_type, filename)).url

        return await self._upload_attachment(attachment, upload)

    async def upload_output_bytes(
        self,
        data: bytes,
        content_type: str | None,
        filename: str,
    ) -> str:
        """Upload ``data`` to the output root and return the file URL."""
        if self.__project is None:
            return (await self.upload_appdata_bytes(data, content_type, filename)).url
        url = f"{self.__project.artifacts_root}{filename}"
        # Inside `artifacts/` only: the rest of the project is read-only to the app.
        if not self.__project.contains(url) or self.__project.is_read_only(url):
            raise ValueError(f"Invalid output file name: {filename}")
        return await self.__file_service.write_bytes(
            url,
            data,
            content_type=content_type or _DEFAULT_CONTENT_TYPE,
            overwrite=True,
        )

    async def upload_appdata_bytes(
        self,
        data: bytes,
        content_type: str | None,
        filename: str,
    ) -> FileItem:
        """Upload ``data`` to the appdata root and return the file metadata."""
        bucket_resp = await self.__dial_client.bucket.get_raw()
        bucket = bucket_resp.appdata or bucket_resp.bucket
        return await self.__dial_client.files.upload(
            url=f"files/{bucket}/{filename}",
            file=(filename, data, content_type),
        )

    @staticmethod
    async def _upload_attachment(
        attachment: Attachment,
        upload: Callable[[bytes, str | None, str], Awaitable[str]],
    ) -> Attachment:
        logger.debug(
            "Uploading attachment: %s, url: %s, data present: %s",
            attachment.title,
            sanitize_url(attachment.url) if attachment.url else None,
            attachment.data is not None,
        )
        if attachment.url is None and attachment.data:
            try:
                attachment_name = attachment.title or generate_attachment_filename(attachment.type)
                url = await upload(_get_bytes(attachment.data), attachment.type, attachment_name)
                # Use URL instead of data for uploaded attachment.
                attachment.data = None
                attachment.url = url
                logger.debug(
                    "Uploaded attachment %s to %s",
                    attachment_name,
                    sanitize_url(attachment.url),
                )
            except Exception:
                logger.exception(
                    "Exception during uploading attachment to DIAL. Original attachment left in place."
                )
        return attachment
