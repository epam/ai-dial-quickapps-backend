"""Request-scoped cache for folder-context listing within one HTTP request."""

from quickapp.common.abstract.folder_listing_provider import ExpandedFolderEntry


class ExpandedContextFileUrls:
    """Mutable per-request cache for folder expansion and get-content allowlisting.

    ``folder_children`` deduplicates DIAL ``list_folder`` calls (keyed by
    ``files/`` URL and ``max_depth``). ``urls`` holds discovered file URLs.
    Populated by ``build_context_entries_async`` during message setup (before
    orchestrator tool wiring) or by ``ensure_expanded_folder_file_urls``.
    """

    __slots__ = ("folder_children", "populated", "urls")

    def __init__(self) -> None:
        self.urls: set[str] = set()
        self.populated: bool = False
        self.folder_children: dict[tuple[str, int], list[ExpandedFolderEntry]] = {}
