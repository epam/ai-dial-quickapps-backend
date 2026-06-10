from quickapp.attachment_processing._expanded_context_file_urls import ExpandedContextFileUrls
from quickapp.common.abstract.folder_listing_provider import (
    ExpandedFolderEntry,
    FolderListingProvider,
)


class NoopFolderListing(FolderListingProvider):
    """Test double that returns a fixed listing (empty by default)."""

    def __init__(self, entries: list[ExpandedFolderEntry] | None = None) -> None:
        self._entries = list(entries or [])

    async def list_folder_entries(
        self, files_folder_url: str, *, max_depth: int
    ) -> list[ExpandedFolderEntry]:
        return list(self._entries)


def empty_expanded_context_file_urls() -> ExpandedContextFileUrls:
    return ExpandedContextFileUrls()
