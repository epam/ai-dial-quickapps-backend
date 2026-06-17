"""URL helpers for admin folder contexts."""

FOLDER_METADATA_MIME = "application/vnd.dial.metadata+json"


def metadata_folder_url_to_files_url(url: str) -> str:
    """Translate a folder context URL to a DIAL files listing URL.

    Folder contexts use the metadata namespace (``metadata/files/.../``).
    ``DialFileService.list_folder`` expects ``files/.../``.
    """
    if url.startswith("metadata/files/"):
        return url.removeprefix("metadata/")
    return url
