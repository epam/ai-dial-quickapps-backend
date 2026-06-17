from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict


class ExpandedFolderEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    is_folder: bool


class FolderListingProvider(ABC):
    """Lists files and subfolders under a DIAL folder URL (``files/.../``)."""

    @abstractmethod
    async def list_folder_entries(
        self, files_folder_url: str, *, max_depth: int
    ) -> list[ExpandedFolderEntry]:
        """Return immediate and nested children (depth-bounded), sorted by URL."""
