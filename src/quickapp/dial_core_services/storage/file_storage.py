from abc import ABC, abstractmethod
from typing import Literal

from aidial_client.types.metadata import FileMetadata
from pydantic import BaseModel, ConfigDict

from quickapp.dial_core_services.exceptions import FileTooLargeError


class FolderEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    is_folder: bool
    size: int | None


class FileStorage(ABC):
    """File I/O against one DIAL storage API, by relative URL.

    No caching and no policy: ``DialFileService`` owns those. Errors are aidial-client's
    typed exceptions (``ResourceNotFoundError``, ``EtagMismatchError``, ``DialException``)
    and ``FileTooLargeError``.
    """

    @abstractmethod
    async def download(self, url: str) -> tuple[bytes, FileMetadata]:
        """The file's bytes and metadata; ``FileTooLargeError`` above the file-loading size
        limit (QuickApps never loads a larger file)."""

    @abstractmethod
    async def upload(
        self,
        url: str,
        content: bytes,
        content_type: str,
        *,
        if_none_match: Literal["*"] | None = None,
        if_match: str | None = None,
    ) -> str:
        """Write the file and return its URL; ``EtagMismatchError`` on a failed precondition."""

    @abstractmethod
    async def delete(self, url: str) -> None: ...

    @abstractmethod
    async def list_level(self, folder_url: str) -> list[FolderEntry]:
        """Direct children of ``folder_url`` (ends with ``/``)."""

    @abstractmethod
    async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None: ...

    @abstractmethod
    async def move(self, source_url: str, destination_url: str, overwrite: bool) -> None: ...


def ensure_within_size_limit(size: int, limit: int) -> None:
    """Raise ``FileTooLargeError`` (a ``ValueError``) when ``size`` exceeds ``limit``."""
    if size > limit:
        raise FileTooLargeError(size, limit)
