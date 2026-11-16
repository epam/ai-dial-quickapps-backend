from typing import Literal, NoReturn

from aidial_client import AsyncDial, DialException, ResourceNotFoundError
from aidial_client.types.metadata import FileItem, FileMetadata
from injector import inject

from quickapp.dial_core_services.storage.file_storage import (
    FileStorage,
    FolderEntry,
    UploadedFile,
    ensure_within_size_limit,
)
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)


@inject
class V1FileStorage(FileStorage):
    """``files/...`` through the v1 files API."""

    def __init__(
        self, dial_client: AsyncDial, size_limit_resolver: FileLoadingSizeLimitResolver
    ) -> None:
        self.__dial_client: AsyncDial = dial_client
        self.__size_limit: int = size_limit_resolver.resolve()

    @staticmethod
    def _reraise_404_as_not_found(exc: DialException) -> NoReturn:
        """Normalize a 404 to ResourceNotFoundError.

        The aidial_client `metadata` resource (used directly by `list_level` and
        indirectly by `files.get_metadata`) registers no `on_http_error` handler, so a 404
        surfaces as a base `DialException`, not `ResourceNotFoundError`. Re-raise it as
        `ResourceNotFoundError` so callers' not-found handling works uniformly.
        """
        if exc.status_code == 404 and not isinstance(exc, ResourceNotFoundError):
            raise ResourceNotFoundError(message=exc.message) from exc
        raise exc

    async def download(self, url: str) -> tuple[bytes, FileMetadata]:
        try:
            metadata = await self.__dial_client.files.get_metadata(url)
        except DialException as e:
            self._reraise_404_as_not_found(e)
        ensure_within_size_limit(metadata.content_length or 0, self.__size_limit)
        data = await (await self.__dial_client.files.download(url)).aget_content()
        return data, metadata

    async def upload(
        self,
        url: str,
        content: bytes,
        content_type: str,
        *,
        if_none_match: Literal["*"] | None = None,
        if_match: str | None = None,
    ) -> UploadedFile:
        filename = url.split("/")[-1]
        metadata = await self.__dial_client.files.upload(
            url=url,
            file=(filename, content, content_type),
            etag_if_none_match=if_none_match,
            etag_if_match=if_match,
        )
        return metadata

    async def delete(self, url: str) -> None:
        await self.__dial_client.files.delete(url)

    async def list_level(self, folder_url: str) -> list[FolderEntry]:
        # metadata.get with the URL verbatim (not files.get_metadata, which runs it through
        # get_api_path) keeps the trailing slash: Core lists a folder only with it.
        try:
            metadata = await self.__dial_client.metadata.get("files", folder_url)
        except DialException as e:
            self._reraise_404_as_not_found(e)
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

    async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        await self.__dial_client.files.copy_to(
            source=source_url,
            destination=destination_url,
            overwrite=overwrite,
        )

    async def move(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        await self.__dial_client.files.move_to(
            source=source_url,
            destination=destination_url,
            overwrite=overwrite,
        )
