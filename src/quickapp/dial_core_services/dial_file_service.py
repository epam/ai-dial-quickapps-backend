import logging
from collections import deque
from pathlib import PurePosixPath
from typing import Literal, NoReturn

from aidial_client import AsyncDial
from aidial_client._exception import DialException, ResourceNotFoundError
from aidial_client.types.metadata import FileItem, FileMetadata
from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.state_holder import StateHolder
from quickapp.common.url_sanitization import sanitize_url_for_log
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
    ):
        self.__dial_client: AsyncDial = dial_client
        self.__state_holder: StateHolder = state_holder
        self.__content_size_limit: int = size_limit_resolver.resolve()

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
        safe_url = sanitize_url_for_log(file_url)
        logger.debug("File url to download: %s", safe_url)
        file_data = self.__state_holder.get_file_data(url=file_url)
        if file_data is not None:
            return file_data, self.__state_holder.get_file_metadata(file_url)
        try:
            logger.debug("Downloading file: %s", safe_url)
            metadata = await self._get_metadata(file_url)
            size = metadata.content_length or 0
            if size > self.__content_size_limit:
                raise ValueError(
                    f"File size {size} exceeds the limit of {self.__content_size_limit} bytes."
                )
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
            metadata = await self._get_metadata(current_url)
            if metadata.node_type != "FOLDER":
                raise ValueError(f"not a folder: {current_url}")
            items: list[FileItem] = metadata.items or []
            for item in items:
                is_folder = item.node_type == "FOLDER"
                item_url = item.url
                if is_folder and not item_url.endswith("/"):
                    item_url = item_url + "/"
                results.append(
                    FolderEntry(
                        url=item_url,
                        is_folder=is_folder,
                        size=item.content_length,
                    )
                )
                if is_folder and depth < max_depth:
                    queue.append((item_url, depth + 1))
        return results

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
        self.invalidate_cache(source_url)

    async def grant_permissions_to_files(
        self, files_to_share: list[str], dial_toolset_id: str
    ) -> None:
        try:
            logger.debug(
                "Granting permissions to files: %s",
                [sanitize_url_for_log(f) for f in files_to_share],
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
