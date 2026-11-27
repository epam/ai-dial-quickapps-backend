import logging
from collections import deque
from pathlib import PurePosixPath

from aidial_client import AsyncDial
from aidial_client.types.metadata import FileMetadata
from injector import inject

from quickapp.common.state_holder import StateHolder
from quickapp.common.url_sanitization import sanitize_url
from quickapp.dial_core_services.storage.file_storage import FileStorage, FolderEntry, UploadedFile

logger = logging.getLogger(__name__)


@inject
class DialFileService:
    """File operations for the agent: the per-request cache and the write semantics over a
    ``FileStorage``, which decides where each URL lives (v1 files or the request's project)."""

    def __init__(
        self,
        dial_client: AsyncDial,
        storage: FileStorage,
        state_holder: StateHolder,
    ):
        self.__dial_client: AsyncDial = dial_client
        self.__storage: FileStorage = storage
        self.__state_holder: StateHolder = state_holder

    async def my_appdata_home(self) -> PurePosixPath | None:
        return await self.__dial_client.my_appdata_home()

    async def download_file(self, file_url: str) -> tuple[bytes, FileMetadata | None]:
        safe_url = sanitize_url(file_url)
        logger.debug("File url to download: %s", safe_url)
        file_data = self.__state_holder.get_file_data(url=file_url)
        if file_data is not None:
            return file_data, self.__state_holder.get_file_metadata(file_url)
        try:
            logger.debug("Downloading file: %s", safe_url)
            file_data, metadata = await self.__storage.download(file_url)
            self.__state_holder.store_file_data(file_url, file_data, metadata)
        except Exception as e:
            logger.error("Failed to download: %s", safe_url, exc_info=True)
            raise e
        return file_data, metadata

    async def write_file(
        self,
        url: str,
        content: str,
        *,
        content_type: str = "text/plain",
        overwrite: bool = False,
        if_match: str | None = None,
    ) -> UploadedFile:
        """Create or overwrite a file with ETag-aware semantics and return its metadata.

        Behaviour:
          * `if_match` given: upload with `If-Match` (caller-driven concurrency
            check, used by the edit tool which already has the etag).
          * `overwrite=False`: upload with `If-None-Match: *` (create only — fail
            if the file already exists).
          * `overwrite=True`: upload unconditionally (create or replace). No
            metadata round-trip, so a not-yet-existing file is simply created.

        Raises `EtagMismatchError` on an `If-None-Match`/`If-Match` failure; other
        DIAL errors propagate unchanged. Cache is invalidated on success.
        """
        data = content.encode("utf-8")
        if if_match is not None:
            uploaded = await self.__storage.upload(url, data, content_type, if_match=if_match)
        elif overwrite:
            uploaded = await self.__storage.upload(url, data, content_type)
        else:
            uploaded = await self.__storage.upload(url, data, content_type, if_none_match="*")
        self.invalidate_cache(url)
        return uploaded

    async def write_bytes(
        self,
        url: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        overwrite: bool = False,
    ) -> UploadedFile:
        """Create or overwrite a file from raw bytes (binary-safe) and return its metadata.

        The bytes counterpart of :meth:`write_file` — used for content that is
        not UTF-8 text (downloaded binaries). Shares the same ETag semantics:
        ``overwrite=False`` uploads with ``If-None-Match: *`` (create only,
        raising ``EtagMismatchError`` if the file exists); ``overwrite=True``
        uploads unconditionally. Cache is invalidated on success.
        """
        uploaded = await self.__storage.upload(
            url, content, content_type, if_none_match=None if overwrite else "*"
        )
        self.invalidate_cache(url)
        return uploaded

    async def delete(self, file_url: str) -> None:
        await self.__storage.delete(file_url)
        self.invalidate_cache(file_url)

    def invalidate_cache(self, file_url: str) -> None:
        self.__state_holder.invalidate_file_data(file_url)

    async def list_folder(self, folder_url: str, max_depth: int = 1) -> list[FolderEntry]:
        """Depth-bounded recursive listing of a folder under DIAL files.

        `folder_url` must end with '/' and begin with 'files/' or 'projects/'. Folders
        at the depth bound are listed but not expanded. Project listings carry no sizes,
        and a missing project folder lists as empty (Core returns no 404 for it).
        """
        results: list[FolderEntry] = []
        queue: deque[tuple[str, int]] = deque([(folder_url, 1)])
        while queue:
            current_url, depth = queue.popleft()
            for entry in await self.__storage.list_level(current_url):
                results.append(entry)
                if entry.is_folder and depth < max_depth:
                    queue.append((entry.url, depth + 1))
        return results

    async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        """Copy a file. Into, out of or inside the request's project it is a download and an
        upload: files only, within the file-loading size limit."""
        await self.__storage.copy(source_url, destination_url, overwrite)
        self.invalidate_cache(destination_url)

    async def move(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        """Move a file.

        Into, out of or inside the request's project, a move is a copy followed by a delete
        of the source, which is not atomic: when the delete fails after the copy, raises
        ``PartialMoveException`` (the destination is written, the source still exists).
        Moving a file onto itself raises ``SameSourceAndDestinationException`` before any
        write, so the source is never deleted.
        """
        try:
            await self.__storage.move(source_url, destination_url, overwrite)
        finally:
            # Also after a partial move: the destination may already be written.
            self.invalidate_cache(source_url)
            self.invalidate_cache(destination_url)

    async def grant_permissions_to_files(
        self, files_to_share: list[str], dial_toolset_id: str
    ) -> None:
        try:
            logger.debug(
                "Granting permissions to files: %s",
                [sanitize_url(f) for f in files_to_share],
            )
            await self.__dial_client.resource_permissions.grant(
                resources=files_to_share,
                receiver=dial_toolset_id,
            )
        except Exception as e:
            logger.error(
                "Failed to grant permissions to the files %s", files_to_share, exc_info=True
            )
            raise e
