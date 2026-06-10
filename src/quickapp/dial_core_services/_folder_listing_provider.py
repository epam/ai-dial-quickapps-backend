import logging

from injector import inject

from quickapp.common.abstract.folder_listing_provider import (
    ExpandedFolderEntry,
    FolderListingProvider,
)
from quickapp.dial_core_services.dial_file_service import DialFileService

logger = logging.getLogger(__name__)

_FOLDER_METADATA_MIME = "application/vnd.dial.metadata+json"


@inject
class DialFolderListingProvider(FolderListingProvider):

    def __init__(self, dial_file_service: DialFileService) -> None:
        self.__dial_file_service: DialFileService = dial_file_service

    async def list_folder_entries(
        self, files_folder_url: str, *, max_depth: int
    ) -> list[ExpandedFolderEntry]:
        try:
            raw_entries = await self.__dial_file_service.list_folder(
                files_folder_url, max_depth=max_depth
            )
        except Exception:
            logger.warning(
                "Failed to list folder context at %s",
                files_folder_url,
                exc_info=True,
            )
            return []

        return sorted(
            (
                ExpandedFolderEntry(
                    url=entry.url,
                    is_folder=entry.is_folder,
                )
                for entry in raw_entries
            ),
            key=lambda item: item.url,
        )


def folder_metadata_mime() -> str:
    return _FOLDER_METADATA_MIME
