from typing import Literal

from aidial_client.types.metadata import FileMetadata

from quickapp.common.project_context import ProjectContext
from quickapp.dial_core_services.storage._transfer import copy_via_download, move_via_download
from quickapp.dial_core_services.storage.file_storage import FileStorage, FolderEntry, UploadedFile


class RoutedFileStorage(FileStorage):
    """Sends each URL to its storage: files of the request's project to ``project_storage``,
    anything else (``projects/…`` of another project included) to ``v1``.

    The only place that decides v1 vs project. A copy or move within one storage uses that
    storage's own; between the two it downloads and uploads.
    """

    def __init__(
        self,
        v1: FileStorage,
        project_storage: FileStorage,
        project: ProjectContext,
    ) -> None:
        self.__v1: FileStorage = v1
        self.__project_storage: FileStorage = project_storage
        self.__project: ProjectContext = project

    def _storage_for(self, url: str) -> FileStorage:
        return self.__project_storage if self.__project.contains(url) else self.__v1

    async def download(self, url: str) -> tuple[bytes, FileMetadata]:
        return await self._storage_for(url).download(url)

    async def upload(
        self,
        url: str,
        content: bytes,
        content_type: str,
        *,
        if_none_match: Literal["*"] | None = None,
        if_match: str | None = None,
    ) -> UploadedFile:
        return await self._storage_for(url).upload(
            url, content, content_type, if_none_match=if_none_match, if_match=if_match
        )

    async def delete(self, url: str) -> None:
        await self._storage_for(url).delete(url)

    async def list_level(self, folder_url: str) -> list[FolderEntry]:
        return await self._storage_for(folder_url).list_level(folder_url)

    async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        source, destination = self._storage_for(source_url), self._storage_for(destination_url)
        if source is destination:
            await source.copy(source_url, destination_url, overwrite)
            return
        await copy_via_download(
            source,
            source_url,
            destination,
            destination_url,
            overwrite=overwrite,
        )

    async def move(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        source, destination = self._storage_for(source_url), self._storage_for(destination_url)
        if source is destination:
            await source.move(source_url, destination_url, overwrite)
            return
        await move_via_download(
            source,
            source_url,
            destination,
            destination_url,
            overwrite=overwrite,
        )
