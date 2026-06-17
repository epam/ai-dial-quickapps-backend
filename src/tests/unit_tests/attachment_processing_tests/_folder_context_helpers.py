from quickapp.attachment_processing._context_entries import (
    ContextEntry,
    build_context_entries_async,
)
from quickapp.attachment_processing._expanded_context_file_urls import ExpandedContextFileUrls
from quickapp.common.abstract.folder_listing_provider import (
    ExpandedFolderEntry,
    FolderListingProvider,
)
from quickapp.config.context import Context


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


async def build_context_entries_for_test(
    contexts: list[Context],
    seen_entries: dict[str, ContextEntry],
    *,
    listing: FolderListingProvider | None = None,
    holder: ExpandedContextFileUrls | None = None,
) -> tuple[set[str], list[ContextEntry]]:
    return await build_context_entries_async(
        contexts,
        seen_entries,
        listing or NoopFolderListing(),
        holder or empty_expanded_context_file_urls(),
    )
