import logging

from aidial_client.types.metadata import FileMetadata
from injector import inject

from quickapp.common.url_sanitization import sanitize_url
from quickapp.dial_core_services.storage.file_storage import FileStorage
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
        storage: FileStorage,
        size_limit_resolver: FileLoadingSizeLimitResolver,
    ) -> None:
        self.__storage: FileStorage = storage
        self.__content_size_limit: int = size_limit_resolver.resolve()

    async def fetch(self, file_url: str) -> tuple[bytes, FileMetadata]:
        logger.debug("Downloading DIAL file: %s", sanitize_url(file_url))
        return await self.__storage.download(file_url, self.__content_size_limit)
