import logging

from aidial_client import AsyncDial
from aidial_client.types.metadata import FileMetadata
from injector import inject

from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)

logger = logging.getLogger(__name__)


@inject
class DialDownloader:
    """Fetches bytes for a DIAL-hosted file URL with the configured size limit.

    Extracted from the previous ``DialFileService.download_file``; consumed by
    :class:`quickapp.file_transfer._file_loader_service.FileLoaderService`,
    which owns the per-request bytes cache.

    Returns the ``FileMetadata`` alongside the bytes so callers can cache it
    next to the data — the ``DialFileService.download_file`` path reads metadata
    out of ``StateHolder`` on cache hits, so omitting it here would make the
    cached entry look like a metadata miss to that consumer and break
    ``If-Match`` upload semantics in ``dial_files_tooling``.
    """

    def __init__(
        self,
        dial_client: AsyncDial,
        size_limit_resolver: FileLoadingSizeLimitResolver,
    ) -> None:
        self.__dial_client: AsyncDial = dial_client
        self.__content_size_limit: int = size_limit_resolver.resolve()

    async def fetch(self, file_url: str) -> tuple[bytes, FileMetadata]:
        logger.debug("Downloading DIAL file: %s", file_url)
        metadata = await self.__dial_client.files.get_metadata(file_url)
        size = metadata.content_length or 0
        if size > self.__content_size_limit:
            raise ValueError(
                f"File size {size} exceeds the limit of {self.__content_size_limit} bytes."
            )
        data = await (await self.__dial_client.files.download(file_url)).aget_content()
        return data, metadata
