import base64
import logging
from collections.abc import Awaitable, Callable

from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.media_types import MediaTypes
from quickapp.common.project_context import PROJECT_CONTEXT
from quickapp.common.url_sanitization import sanitize_url
from quickapp.common.utils import generate_attachment_filename
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_core_services.storage.file_storage import UploadedFile

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
    """Uploads generated files to DIAL storage, flat under one of two roots.

    - **Output root** (``upload_output_*``): files produced for the user (MCP tool files,
      REST response files, interpreter charts). The current project's ``artifacts/`` in a
      project chat, so Chat lists them as the project's Outputs; the appdata root otherwise.
    - **Appdata root** (``upload_appdata_*``): internal files (large-result offloads,
      promoted external URLs). Always appdata, project or not.

    Both roots keep the same naming and overwrite behaviour: ``{root}{filename}``, written
    unconditionally through ``DialFileService`` (which routes v1 and project URLs), so a
    same-named file is replaced.
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
        self.__appdata_root: str | None = None

    async def upload_output_attachment(self, attachment: Attachment) -> Attachment:
        """Upload the inline ``data`` of ``attachment`` to the output root (see the class doc).

        On failure the original attachment is returned unchanged.
        """
        return await self._upload_attachment(attachment, self.upload_output_bytes)

    async def upload_appdata_attachment(self, attachment: Attachment) -> Attachment:
        """Upload the inline ``data`` of ``attachment`` to the appdata root.

        On failure the original attachment is returned unchanged.
        """
        return await self._upload_attachment(attachment, self.upload_appdata_bytes)

    async def upload_output_bytes(
        self,
        data: bytes,
        content_type: str | None,
        filename: str,
    ) -> UploadedFile:
        """Upload ``data`` to the output root and return the file's metadata."""
        if self.__project is None:
            return await self.upload_appdata_bytes(data, content_type, filename)
        url = f"{self.__project.artifacts_root}{filename}"
        # A name with an unsafe segment (``..``, an encoded ``/``) could leave `artifacts/`:
        # the project's URLs never have one.
        if not self.__project.contains(url):
            raise ValueError(f"Invalid output file name: {filename}")
        return await self._write(url, data, content_type)

    async def upload_appdata_bytes(
        self,
        data: bytes,
        content_type: str | None,
        filename: str,
    ) -> UploadedFile:
        """Upload ``data`` to the appdata root and return the file's metadata."""
        return await self._write(f"{await self._appdata_root()}{filename}", data, content_type)

    async def _write(self, url: str, data: bytes, content_type: str | None) -> UploadedFile:
        return await self.__file_service.write_bytes(
            url, data, content_type=content_type or MediaTypes.UNKNOWN_BINARY, overwrite=True
        )

    async def _appdata_root(self) -> str:
        """``files/{appdata}/``, asked once per request (the service is request-scoped)."""
        if self.__appdata_root is None:
            bucket_resp = await self.__dial_client.bucket.get_raw()
            self.__appdata_root = f"files/{bucket_resp.appdata or bucket_resp.bucket}/"
        return self.__appdata_root

    @staticmethod
    async def _upload_attachment(
        attachment: Attachment,
        upload: Callable[[bytes, str | None, str], Awaitable[UploadedFile]],
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
                uploaded = await upload(
                    _get_bytes(attachment.data), attachment.type, attachment_name
                )
                # Use URL instead of data for uploaded attachment.
                attachment.data = None
                attachment.url = uploaded.url
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
