from quickapp.common.utils import canonical_url
from quickapp.dial_core_services.exceptions import (
    FileTooLargeError,
    PartialMoveException,
    ProjectFileOperationException,
    ProjectFileTooLargeException,
    SameSourceAndDestinationException,
)
from quickapp.dial_core_services.storage.file_storage import FileStorage


async def copy_via_download(
    source: FileStorage,
    source_url: str,
    destination: FileStorage,
    destination_url: str,
    *,
    overwrite: bool,
) -> None:
    """Copy a file into, out of or inside a project.

    Core's copy/move endpoints don't cover projects, so this downloads and uploads,
    which only works within the file-loading size limit, and only for files.
    """
    if source_url.endswith("/"):
        raise ProjectFileOperationException(
            "copying or moving folders in a project is not supported"
        )
    if canonical_url(source_url) == canonical_url(destination_url):
        raise SameSourceAndDestinationException(source_url)
    try:
        data, metadata = await source.download(source_url)
    except FileTooLargeError as e:
        raise ProjectFileTooLargeException(source_url, e.limit) from e
    await destination.upload(
        destination_url,
        data,
        metadata.content_type or "application/octet-stream",
        if_none_match=None if overwrite else "*",
    )


async def move_via_download(
    source: FileStorage,
    source_url: str,
    destination: FileStorage,
    destination_url: str,
    *,
    overwrite: bool,
) -> None:
    """Move a file as a copy followed by a delete of the source, which is not atomic.

    When the delete fails after the copy, raises ``PartialMoveException`` (the destination
    is written, the source still exists). Moving a file onto itself raises
    ``SameSourceAndDestinationException`` before any write, so the source is never deleted.
    """
    await copy_via_download(
        source,
        source_url,
        destination,
        destination_url,
        overwrite=overwrite,
    )
    try:
        await source.delete(source_url)
    except Exception as e:
        raise PartialMoveException(source_url, destination_url) from e
