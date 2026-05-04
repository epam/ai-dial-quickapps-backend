import logging
from typing import Literal

from aidial_client import AsyncDial
from aidial_client.types.metadata import FileMetadata
from injector import inject

from quickapp.common.file_loading_size_limit_resolver import FileLoadingSizeLimitResolver
from quickapp.common.state_holder import StateHolder

logger = logging.getLogger(__name__)


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

    async def upload_text(
        self,
        url: str,
        content: str,
        *,
        if_none_match: Literal["*"] | None = None,
        if_match: str | None = None,
    ) -> str:
        encoded = content.encode("utf-8")
        filename = url.split("/")[-1]
        metadata = await self.__dial_client.files.upload(
            url=url,
            file=(filename, encoded, "text/plain"),
            etag_if_none_match=if_none_match,
            etag_if_match=if_match,
        )
        return metadata.url

    def invalidate_cache(self, file_url: str) -> None:
        self.__state_holder.invalidate_file_data(file_url)

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
