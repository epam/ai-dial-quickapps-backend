from typing import Literal

import httpx
from aidial_client import AsyncDial, EtagMismatchError
from aidial_client.types.file import FileDownloadResponse
from aidial_client.types.metadata import FileMetadata
from injector import inject

from quickapp.common.project_context import PROJECT_CONTEXT
from quickapp.common.utils import canonical_url
from quickapp.dial_core_services._project_files import ProjectFilesClient, project_file_metadata
from quickapp.dial_core_services.exceptions import FileAccessDeniedError
from quickapp.dial_core_services.storage._transfer import copy_via_download, move_via_download
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
class ProjectFileStorage(FileStorage):
    """Files of the request's project (``projects/{bucket}/{path}/files/...``) through the v2
    project API, as the agent sees them.

    The agent reads only ``context/`` and ``artifacts/`` (``ProjectContext.can_read``):
    listing the project folder returns just those, without a request, and reading, listing
    or granting any other path of the project (``PROJECT.md``, ``conversations/``) raises
    ``FileAccessDeniedError`` before any request, whether the path exists or not.
    ``read_instructions`` is the one read outside that view, for the system prompt. Writes
    aren't checked here: the agent writes only under its home
    (``HomePathResolver.resolve_write_url``).
    """

    def __init__(
        self,
        dial_client: AsyncDial,
        project_files: ProjectFilesClient,
        size_limit_resolver: FileLoadingSizeLimitResolver,
        project: PROJECT_CONTEXT,
    ) -> None:
        self.__dial_client: AsyncDial = dial_client
        self.__project_files: ProjectFilesClient = project_files
        self.__size_limit: int = size_limit_resolver.resolve()
        self.__project: PROJECT_CONTEXT = project

    async def download(self, url: str) -> tuple[bytes, FileMetadata]:
        self.__ensure_readable(url)
        return await self.__download(url)

    async def read_instructions(self) -> tuple[bytes, FileMetadata]:
        """The project's ``PROJECT.md``, for the system prompt; not readable by the agent."""
        if self.__project is None:
            raise ValueError("read_instructions needs a project in the request")
        return await self.__download(self.__project.instructions_url)

    async def __download(self, url: str) -> tuple[bytes, FileMetadata]:
        async with self.__project_files.stream(url) as response:
            return await read_within_size_limit(response, url, self.__size_limit)

    def __ensure_readable(self, url: str) -> None:
        if self.__project is None or not self.__project.can_read(url):
            raise FileAccessDeniedError(
                "only the current project's context/ and artifacts/ folders are readable"
            )

    async def upload(
        self,
        url: str,
        content: bytes,
        content_type: str,
        *,
        if_none_match: Literal["*"] | None = None,
        if_match: str | None = None,
    ) -> UploadedFile:
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
        # Core's v2 PUT returns no file metadata (only the project's ETag), so it is built
        # from what was written. The URL is canonical, like v1's `metadata.url`; the file's
        # own ETag is unknown here.
        return project_file_metadata(
            canonical_url(url), httpx.Headers({"content-type": content_type}), len(content)
        )

    async def delete(self, url: str) -> None:
        await self.__project_files.delete(url)

    async def list_level(self, folder_url: str) -> list[FolderEntry]:
        project = self.__project
        if project is not None and canonical_url(folder_url) == project.content_root:
            # The layout is fixed: the agent sees these two, whether they exist yet or not.
            return [
                FolderEntry(url=root, is_folder=True, size=None)
                for root in (project.context_root, project.artifacts_root)
            ]
        self.__ensure_readable(folder_url)
        # No sizes in project listings; a missing folder lists as empty (Core returns no 404).
        return [
            FolderEntry(url=item.url, is_folder=item.is_folder, size=None)
            for item in await self.__project_files.list(folder_url)
        ]

    async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        await copy_via_download(self, source_url, self, destination_url, overwrite=overwrite)

    async def move(self, source_url: str, destination_url: str, overwrite: bool) -> None:
        await move_via_download(self, source_url, self, destination_url, overwrite=overwrite)

    async def grant_read(self, urls: list[str], receiver: str) -> None:
        """The receiver reads with its own grant, not through this view, so only readable URLs
        are granted, in canonical form. Core's per-request grant takes any resource URL."""
        for url in urls:
            self.__ensure_readable(url)
        await self.__dial_client.resource_permissions.grant(
            resources=[canonical_url(url) for url in urls], receiver=receiver
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
