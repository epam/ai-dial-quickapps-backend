from typing import Literal

from aidial_client.types.metadata import FileMetadata

from quickapp.common.project_context import (
    CURRENT_PROJECT_ONLY_MESSAGE,
    ProjectContext,
    current_project_url,
)
from quickapp.dial_core_services.exceptions import ProjectFileOperationException
from quickapp.dial_core_services.storage._transfer import copy_via_download, move_via_download
from quickapp.dial_core_services.storage.file_storage import FileStorage, FolderEntry, UploadedFile


class RoutedFileStorage(FileStorage):
    """Sends each URL to its storage: ``files/…`` to ``v1``, files of the request's project to
    ``project_storage`` (in canonical form). Any other ``projects/…`` URL, or any at all
    without a project, is refused: QuickApps touches only the request's project (D8).

    The only place that decides v1 vs project. A copy or move within one storage uses that
    storage's own; between the two it downloads and uploads.
    """

    def __init__(
        self,
        v1: FileStorage,
        project_storage: FileStorage,
        project: ProjectContext | None,
    ) -> None:
        self.__v1: FileStorage = v1
        self.__project_storage: FileStorage = project_storage
        self.__project: ProjectContext | None = project

    def _route(self, url: str) -> tuple[FileStorage, str]:
        """The storage for ``url`` and the URL to give it."""
        if not url.startswith("projects/"):
            return self.__v1, url
        project_url = current_project_url(self.__project, url)
        if project_url is None:
            # 403, so the file tools report it like Core's own refusal ("access denied").
            raise ProjectFileOperationException(CURRENT_PROJECT_ONLY_MESSAGE, status_code=403)
        return self.__project_storage, project_url

    async def download(self, url: str) -> tuple[bytes, FileMetadata]:
        storage, url = self._route(url)
        return await storage.download(url)

    async def upload(
        self,
        url: str,
        content: bytes,
        content_type: str,
        *,
        if_none_match: Literal["*"] | None = None,
        if_match: str | None = None,
    ) -> UploadedFile:
        storage, url = self._route(url)
        return await storage.upload(
            url, content, content_type, if_none_match=if_none_match, if_match=if_match
        )

    async def delete(self, url: str) -> None:
        storage, url = self._route(url)
        await storage.delete(url)

    async def list_level(self, folder_url: str) -> list[FolderEntry]:
        storage, folder_url = self._route(folder_url)
        return await storage.list_level(folder_url)

    async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        source, source_url = self._route(source_url)
        destination, destination_url = self._route(destination_url)
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
        source, source_url = self._route(source_url)
        destination, destination_url = self._route(destination_url)
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
