"""Pure path/string helpers shared by the DIAL file tools.

These are deliberately free of DI/IO so they live here rather than on the
``_DialFileTool`` base class (which holds the download/resolution behaviour).
"""


def is_root_reference(path: str) -> bool:
    """Whether the path denotes the agent home directory itself ('', '.', './', '/')."""
    return path.strip() in ("", ".", "./", "/")


def relative_to(url: str, folder_url: str) -> str:
    """Path of `url` relative to the search root `folder_url` (used for glob matching)."""
    if url.startswith(folder_url):
        return url[len(folder_url) :]
    return url
