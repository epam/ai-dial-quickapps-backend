from typing import Literal

from aidial_client._exception import EtagMismatchError
from aidial_client.helpers.storage_resource import _percent_encode_relative_url
from aidial_client.types.file import FileDownloadResponse
from aidial_client.types.metadata import FileMetadata
from injector import inject

from quickapp.dial_core_services._project_files import ProjectFilesClient, project_file_metadata
from quickapp.dial_core_services.storage._transfer import copy_via_download, move_via_download
from quickapp.dial_core_services.storage.file_storage import (
    FileStorage,
    FolderEntry,
    ensure_within_size_limit,
)
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)


@inject
class ProjectFileStorage(FileStorage):
    """Files of a project (``projects/{bucket}/{path}/files/...``) through the v2 project API."""

    def __init__(
        self,
        project_files: ProjectFilesClient,
        size_limit_resolver: FileLoadingSizeLimitResolver,
    ) -> None:
        self.__project_files: ProjectFilesClient = project_files
        self.__size_limit_resolver: FileLoadingSizeLimitResolver = size_limit_resolver

    async def download(self, url: str, max_bytes: int) -> tuple[bytes, FileMetadata]:
        async with self.__project_files.stream(url) as response:
            return await read_within_size_limit(response, url, max_bytes)

    async def upload(
        self,
        url: str,
        content: bytes,
        content_type: str,
        *,
        if_none_match: Literal["*"] | None = None,
        if_match: str | None = None,
    ) -> str:
        """Check the precondition, then one plain PUT.

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
        # Same form v1 returns in `metadata.url`.
        return _percent_encode_relative_url(url)

    async def delete(self, url: str) -> None:
        await self.__project_files.delete(url)

    async def list_level(self, folder_url: str) -> list[FolderEntry]:
        # No sizes in project listings; a missing folder lists as empty (Core returns no 404).
        return [
            FolderEntry(url=item.url, is_folder=item.is_folder, size=None)
            for item in await self.__project_files.list(folder_url)
        ]

    async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        await copy_via_download(
            self,
            source_url,
            self,
            destination_url,
            overwrite=overwrite,
            max_bytes=self.__size_limit_resolver.resolve(),
        )

    async def move(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        await move_via_download(
            self,
            source_url,
            self,
            destination_url,
            overwrite=overwrite,
            max_bytes=self.__size_limit_resolver.resolve(),
        )


async def read_within_size_limit(
    response: FileDownloadResponse, url: str, limit: int
) -> tuple[bytes, FileMetadata]:
    """Read a streamed project file within ``limit``.

    Projects have no per-file metadata call, so the size comes from ``Content-Length``,
    checked before the body is read. Without the header, reading stops once the limit is
    passed.
    """
    declared = response.headers.get("content-length")
    if declared is not None:
        ensure_within_size_limit(int(declared), limit)
    data = bytearray()
    async for chunk in response:
        data += chunk
        ensure_within_size_limit(len(data), limit)
    return bytes(data), project_file_metadata(url, response.headers, len(data))
