import logging

from aidial_client import AsyncDial
from aidial_client.types.metadata import FileMetadata
from injector import inject

from quickapp.common.project_context import PROJECT_CONTEXT
from quickapp.common.url_sanitization import sanitize_url
from quickapp.dial_core_services._project_files import ProjectFilesClient
from quickapp.dial_core_services.exceptions import FileTooLargeError
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
        project_files: ProjectFilesClient,
        project: PROJECT_CONTEXT,
    ) -> None:
        self.__dial_client: AsyncDial = dial_client
        self.__content_size_limit: int = size_limit_resolver.resolve()
        self.__project_files: ProjectFilesClient = project_files
        self.__project: PROJECT_CONTEXT = project

    async def fetch(self, file_url: str) -> tuple[bytes, FileMetadata]:
        logger.debug("Downloading DIAL file: %s", sanitize_url(file_url))
        if self.__project is not None and self.__project.contains(file_url):
            # Only the request's own project goes to v2. No per-file metadata endpoint
            # there: the size is known only after the download.
            data, metadata = await self.__project_files.download(file_url)
            ensure_within_size_limit(len(data), self.__content_size_limit)
            return data, metadata
        metadata = await self.__dial_client.files.get_metadata(file_url)
        ensure_within_size_limit(metadata.content_length or 0, self.__content_size_limit)
        data = await (await self.__dial_client.files.download(file_url)).aget_content()
        return data, metadata


def ensure_within_size_limit(size: int, limit: int) -> None:
    """Raise ``FileTooLargeError`` (a ``ValueError``) when ``size`` exceeds ``limit``."""
    if size > limit:
        raise FileTooLargeError(size, limit)
