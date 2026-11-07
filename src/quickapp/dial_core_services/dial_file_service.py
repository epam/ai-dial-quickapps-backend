import logging
from collections import deque
from pathlib import PurePosixPath
from typing import Literal, NoReturn

from aidial_client import AsyncDial
from aidial_client._exception import DialException, EtagMismatchError, ResourceNotFoundError
from aidial_client.helpers.storage_resource import _percent_encode_relative_url
from aidial_client.types.metadata import FileItem, FileMetadata
from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.project_context import PROJECT_CONTEXT
from quickapp.common.state_holder import StateHolder
from quickapp.common.url_sanitization import sanitize_url
from quickapp.dial_core_services._project_files import ProjectFilesClient
from quickapp.dial_core_services.dial_downloader import ensure_within_size_limit
from quickapp.dial_core_services.exceptions import (
    FileTooLargeError,
    PartialMoveException,
    ProjectFileOperationException,
    ProjectFileTooLargeException,
    SameSourceAndDestinationException,
)
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)

logger = logging.getLogger(__name__)


class FolderEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    is_folder: bool
    size: int | None


@inject
class DialFileService:

    def __init__(
        self,
        dial_client: AsyncDial,
        state_holder: StateHolder,
        size_limit_resolver: FileLoadingSizeLimitResolver,
        project_files: ProjectFilesClient,
        project: PROJECT_CONTEXT,
    ):
        self.__dial_client: AsyncDial = dial_client
        self.__state_holder: StateHolder = state_holder
        self.__content_size_limit: int = size_limit_resolver.resolve()
        self.__project_files: ProjectFilesClient = project_files
        self.__project: PROJECT_CONTEXT = project

    def _in_project(self, url: str) -> bool:
        """Whether ``url`` is a file or folder of the request's project.

        Only those go to the v2 project API. Any other URL, ``projects/…`` included, takes
        the v1 path unchanged.
        """
        return self.__project is not None and self.__project.contains(url)

    async def my_appdata_home(self) -> PurePosixPath | None:
        return await self.__dial_client.my_appdata_home()

    @staticmethod
    def _reraise_404_as_not_found(exc: DialException) -> NoReturn:
        """Normalize a 404 to ResourceNotFoundError.

        The aidial_client `metadata` resource (used directly by `list_folder` and
        indirectly by `files.get_metadata`) registers no `on_http_error` handler, so a 404
        surfaces as a base `DialException`, not `ResourceNotFoundError`. Re-raise it as
        `ResourceNotFoundError` so callers' not-found handling works uniformly.
        """
        if exc.status_code == 404 and not isinstance(exc, ResourceNotFoundError):
            raise ResourceNotFoundError(message=exc.message) from exc
        raise exc

    async def _get_metadata(self, url: str) -> FileMetadata:
        """Fetch file or folder metadata, normalizing a 404 to ResourceNotFoundError.

        Calls metadata.get with the URL verbatim (rather than files.get_metadata, which
        runs it through get_api_path) so a trailing slash is preserved — DIAL Core
        distinguishes a folder (trailing '/', returns .items) from a file. Callers always
        pass pre-resolved relative 'files/...' URLs, so get_api_path normalization is moot.
        """
        try:
            return await self.__dial_client.metadata.get("files", url)
        except DialException as e:
            self._reraise_404_as_not_found(e)

    async def download_file(self, file_url: str) -> tuple[bytes, FileMetadata | None]:
        safe_url = sanitize_url(file_url)
        logger.debug("File url to download: %s", safe_url)
        file_data = self.__state_holder.get_file_data(url=file_url)
        if file_data is not None:
            return file_data, self.__state_holder.get_file_metadata(file_url)
        try:
            logger.debug("Downloading file: %s", safe_url)
            if self._in_project(file_url):
                # No per-file metadata endpoint: the size is known only after the download.
                # Check it before the download once aidial-client's stream() maps error
                # statuses correctly.
                file_data, metadata = await self.__project_files.download(file_url)
                ensure_within_size_limit(len(file_data), self.__content_size_limit)
            else:
                metadata = await self._get_metadata(file_url)
                ensure_within_size_limit(metadata.content_length or 0, self.__content_size_limit)
                file_data = await (await self.__dial_client.files.download(file_url)).aget_content()
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
    ) -> str:
        """Create or overwrite a file with ETag-aware semantics.

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
        if if_match is not None:
            uploaded_url = await self._upload_text(url, content, content_type, if_match=if_match)
        elif overwrite:
            uploaded_url = await self._upload_text(url, content, content_type)
        else:
            uploaded_url = await self._upload_text(url, content, content_type, if_none_match="*")
        self.invalidate_cache(url)
        return uploaded_url

    async def write_bytes(
        self,
        url: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        overwrite: bool = False,
    ) -> str:
        """Create or overwrite a file from raw bytes (binary-safe).

        The bytes counterpart of :meth:`write_file` — used for content that is
        not UTF-8 text (downloaded binaries). Shares the same ETag semantics:
        ``overwrite=False`` uploads with ``If-None-Match: *`` (create only,
        raising ``EtagMismatchError`` if the file exists); ``overwrite=True``
        uploads unconditionally. Cache is invalidated on success.
        """
        if overwrite:
            uploaded_url = await self._upload_bytes(url, content, content_type)
        else:
            uploaded_url = await self._upload_bytes(url, content, content_type, if_none_match="*")
        self.invalidate_cache(url)
        return uploaded_url

    async def _upload_text(
        self,
        url: str,
        content: str,
        content_type: str,
        *,
        if_none_match: Literal["*"] | None = None,
        if_match: str | None = None,
    ) -> str:
        return await self._upload_bytes(
            url,
            content.encode("utf-8"),
            content_type,
            if_none_match=if_none_match,
            if_match=if_match,
        )

    async def _upload_bytes(
        self,
        url: str,
        content: bytes,
        content_type: str,
        *,
        if_none_match: Literal["*"] | None = None,
        if_match: str | None = None,
    ) -> str:
        if self._in_project(url):
            await self._upload_project_file(
                url,
                content,
                content_type,
                if_none_match=if_none_match,
                if_match=if_match,
            )
            # Same form v1 returns in `metadata.url`.
            return _percent_encode_relative_url(url)
        filename = url.split("/")[-1]
        metadata = await self.__dial_client.files.upload(
            url=url,
            file=(filename, content, content_type),
            etag_if_none_match=if_none_match,
            etag_if_match=if_match,
        )
        return metadata.url

    async def _upload_project_file(
        self,
        url: str,
        content: bytes,
        content_type: str,
        *,
        if_none_match: Literal["*"] | None,
        if_match: str | None,
    ) -> None:
        """Write a file of the request's project: check the precondition, then one plain PUT.

        Core checks ``If-Match`` / ``If-None-Match`` on a project file against the ETag of
        the whole project, which any write to the project changes. So the file's own state
        is checked here, and a failed check raises ``EtagMismatchError`` as v1 does. Not
        atomic: a write to the same file between the check and the PUT wins. Follow-up: one
        conditional PUT once Core checks preconditions per file (epic I#656).
        """
        if if_none_match == "*" and await self.__project_files.file_etag(url) is not None:
            raise EtagMismatchError(message=f"File already exists: {url}")
        if if_match is not None and await self.__project_files.file_etag(url) != if_match:
            raise EtagMismatchError(message=f"File has changed: {url}")
        await self.__project_files.put(url, content, content_type)

    async def delete(self, file_url: str) -> None:
        if self._in_project(file_url):
            await self.__project_files.delete(file_url)
        else:
            await self.__dial_client.files.delete(file_url)
        self.invalidate_cache(file_url)

    def invalidate_cache(self, file_url: str) -> None:
        self.__state_holder.invalidate_file_data(file_url)

    async def list_folder(self, folder_url: str, max_depth: int = 1) -> list[FolderEntry]:
        """Depth-bounded recursive listing of a folder under DIAL files.

        `folder_url` must end with '/' and begin with 'files/' or 'projects/'. Folders
        at the depth bound are listed but not expanded. Project listings carry no sizes,
        and a missing project folder lists as empty (Core returns no 404 for it).
        """
        list_level = (
            self._list_project_level if self._in_project(folder_url) else self._list_files_level
        )
        results: list[FolderEntry] = []
        queue: deque[tuple[str, int]] = deque([(folder_url, 1)])
        while queue:
            current_url, depth = queue.popleft()
            for entry in await list_level(current_url):
                results.append(entry)
                if entry.is_folder and depth < max_depth:
                    queue.append((entry.url, depth + 1))
        return results

    async def _list_files_level(self, folder_url: str) -> list[FolderEntry]:
        metadata = await self._get_metadata(folder_url)
        if metadata.node_type != "FOLDER":
            raise ValueError(f"not a folder: {folder_url}")
        items: list[FileItem] = metadata.items or []
        entries: list[FolderEntry] = []
        for item in items:
            is_folder = item.node_type == "FOLDER"
            item_url = item.url
            if is_folder and not item_url.endswith("/"):
                item_url = item_url + "/"
            entries.append(FolderEntry(url=item_url, is_folder=is_folder, size=item.content_length))
        return entries

    async def _list_project_level(self, folder_url: str) -> list[FolderEntry]:
        return [
            FolderEntry(url=item.url, is_folder=item.is_folder, size=None)
            for item in await self.__project_files.list(folder_url)
        ]

    async def _copy_via_download(
        self, source_url: str, destination_url: str, overwrite: bool
    ) -> None:
        """Copy a file into, out of or inside the request's project.

        Core's copy/move endpoints don't cover projects, so this downloads and uploads,
        which only works within the file-loading size limit, and only for files.
        """
        if source_url.endswith("/"):
            raise ProjectFileOperationException(
                "copying or moving folders in a project is not supported"
            )
        if _percent_encode_relative_url(source_url) == _percent_encode_relative_url(
            destination_url
        ):
            raise SameSourceAndDestinationException(source_url)
        try:
            data, metadata = await self.download_file(source_url)
        except FileTooLargeError as e:
            raise ProjectFileTooLargeException(source_url, e.limit) from e
        content_type = (metadata.content_type if metadata else None) or "application/octet-stream"
        await self.write_bytes(
            destination_url, data, content_type=content_type, overwrite=overwrite
        )

    async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        if self._in_project(source_url) or self._in_project(destination_url):
            await self._copy_via_download(source_url, destination_url, overwrite)
            return
        await self.__dial_client.files.copy_to(
            source=source_url,
            destination=destination_url,
            overwrite=overwrite,
        )

    async def move(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        """Move a file.

        Into, out of or inside the request's project, a move is a copy followed by a delete
        of the source, which is not atomic: when the delete fails after the copy, raises
        ``PartialMoveException`` (the destination is written, the source still exists).
        Moving a file onto itself raises ``SameSourceAndDestinationException`` before any
        write, so the source is never deleted.
        """
        if self._in_project(source_url) or self._in_project(destination_url):
            await self._copy_via_download(source_url, destination_url, overwrite)
            try:
                await self.delete(source_url)
            except Exception as e:
                raise PartialMoveException(source_url, destination_url) from e
            return
        await self.__dial_client.files.move_to(
            source=source_url,
            destination=destination_url,
            overwrite=overwrite,
        )
        self.invalidate_cache(source_url)

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
