import logging
from collections import deque
from pathlib import PurePosixPath
from typing import Literal

from aidial_client import AsyncDial
from aidial_client._exception import EtagMismatchError, ResourceNotFoundError
from aidial_client._internal_types._http_request import FinalRequestOptions
from aidial_client.types.metadata import FileItem, FileMetadata
from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.file_loading_size_limit_resolver import FileLoadingSizeLimitResolver
from quickapp.common.state_holder import StateHolder

logger = logging.getLogger(__name__)


class FolderEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    name: str
    is_folder: bool
    size: int | None


@inject
class DialFileService:

    def __init__(
        self,
        dial_client: AsyncDial,
        state_holder: StateHolder,
        size_limit_resolver: FileLoadingSizeLimitResolver,
    ):
        self.__dial_client: AsyncDial = dial_client
        self.__state_holder: StateHolder = state_holder
        self.__content_size_limit: int = size_limit_resolver.resolve()

    async def my_appdata_home(self) -> PurePosixPath | None:
        return await self.__dial_client.my_appdata_home()

    async def download_file(self, file_url: str) -> tuple[bytes, FileMetadata | None]:
        logger.debug(f"File url to download url:{file_url}")
        file_data = self.__state_holder.get_file_data(url=file_url)
        if file_data is not None:
            return file_data, self.__state_holder.get_file_metadata(file_url)
        try:
            logger.debug(f"Downloading file:{file_url}")
            metadata = await self.__dial_client.files.get_metadata(file_url)
            size = metadata.content_length or 0
            if size > self.__content_size_limit:
                raise ValueError(
                    f"File size {size} exceeds the limit of {self.__content_size_limit} bytes."
                )
            file_data = await (await self.__dial_client.files.download(file_url)).aget_content()
            self.__state_holder.store_file_data(file_url, file_data, metadata)
        except Exception as e:
            logger.error("Failed to download: %s", file_url, exc_info=True)
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
          * `overwrite=False`: upload with `If-None-Match: *` (fail if the file
            exists).
          * `overwrite=True`: fetch current metadata; if the file exists, upload
            with `If-Match: <etag>`; otherwise upload with `If-None-Match: *`.

        Raises `EtagMismatchError` on `If-None-Match`/`If-Match` failure; other
        DIAL errors propagate unchanged. Cache is invalidated on success.
        """
        if if_match is not None:
            uploaded_url = await self._upload_text(url, content, content_type, if_match=if_match)
        elif not overwrite:
            uploaded_url = await self._upload_text(url, content, content_type, if_none_match="*")
        else:
            try:
                metadata = await self.__dial_client.files.get_metadata(url)
                etag: str | None = metadata.etag
            except ResourceNotFoundError:
                etag = None
            if etag is None:
                uploaded_url = await self._upload_text(
                    url, content, content_type, if_none_match="*"
                )
            else:
                uploaded_url = await self._upload_text(url, content, content_type, if_match=etag)
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
        encoded = content.encode("utf-8")
        filename = url.split("/")[-1]
        metadata = await self.__dial_client.files.upload(
            url=url,
            file=(filename, encoded, content_type),
            etag_if_none_match=if_none_match,
            etag_if_match=if_match,
        )
        return metadata.url

    async def delete(self, file_url: str) -> None:
        await self.__dial_client.files.delete(file_url)
        self.invalidate_cache(file_url)

    def invalidate_cache(self, file_url: str) -> None:
        self.__state_holder.invalidate_file_data(file_url)

    async def list_folder(self, folder_url: str, max_depth: int = 1) -> list[FolderEntry]:
        """Depth-bounded recursive listing of a folder under DIAL files.

        `folder_url` must end with '/' and begin with 'files/'. Folders at the
        depth bound are listed but not expanded.
        """
        results: list[FolderEntry] = []
        queue: deque[tuple[str, int]] = deque([(folder_url, 1)])
        while queue:
            current_url, depth = queue.popleft()
            metadata = await self.__dial_client.metadata.get("files", current_url)
            if metadata.node_type != "FOLDER":
                raise ValueError(f"not a folder: {current_url}")
            items: list[FileItem] = metadata.items or []
            for item in items:
                is_folder = item.node_type == "FOLDER"
                item_name = item.name or ""
                item_url = item.url
                if is_folder and not item_url.endswith("/"):
                    item_url = item_url + "/"
                results.append(
                    FolderEntry(
                        url=item_url,
                        name=item_name,
                        is_folder=is_folder,
                        size=item.content_length,
                    )
                )
                if is_folder and depth < max_depth:
                    queue.append((item_url, depth + 1))
        return results

    async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        await self.__dial_client._http_client.request(
            cast_to=type(None),
            options=FinalRequestOptions(
                method="POST",
                url="/v1/ops/resource/copy",
                json_data={
                    "sourceUrl": source_url,
                    "destinationUrl": destination_url,
                    "overwrite": overwrite,
                },
            ),
        )

    async def move(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        await self.__dial_client._http_client.request(
            cast_to=type(None),
            options=FinalRequestOptions(
                method="POST",
                url="/v1/ops/resource/move",
                json_data={
                    "sourceUrl": source_url,
                    "destinationUrl": destination_url,
                    "overwrite": overwrite,
                },
            ),
        )
        self.invalidate_cache(source_url)

    async def grant_permissions_to_files(
        self, files_to_share: list[str], dial_toolset_id: str
    ) -> None:
        try:
            logger.debug(f"Granting permissions to files: {files_to_share}")
            await self.__dial_client.resource_permissions.grant(
                resources=files_to_share,
                receiver=dial_toolset_id,
            )
        except Exception as e:
            logger.error(
                "Failed to grant permissions to the files %s", files_to_share, exc_info=True
            )
            raise e


# Re-export for service consumers
__all__ = [
    "DialFileService",
    "FolderEntry",
    "EtagMismatchError",
    "ResourceNotFoundError",
]
