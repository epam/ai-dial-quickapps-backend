"""DI-free helpers shared by the DIAL file tools: path math and listing rendering.

These have no dependency on `self`/DI, so they live here rather than on the
`_DialFileTool` base class (which holds the download/resolution behaviour).
"""

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import FolderEntry


def is_root_reference(path: str) -> bool:
    """Whether the path denotes the agent home directory itself ('', '.', './', '/')."""
    return path.strip() in ("", ".", "./", "/")


def validate_relative_path(path: str) -> None:
    """Reject relative paths that are unsafe or malformed (leading '/', '..', etc.)."""
    if path != path.strip():
        raise InvalidToolCallParameterException(
            "path", "path must not have leading/trailing whitespace"
        )
    if path.startswith("/"):
        raise InvalidToolCallParameterException("path", "path must not start with '/'")
    segments = path.split("/")
    if ".." in segments:
        raise InvalidToolCallParameterException("path", "path must not contain '..'")
    # Trailing '' (caused by a trailing '/') is allowed to denote a folder URL.
    if "" in segments[:-1]:
        raise InvalidToolCallParameterException("path", "path must not contain empty segments")


def reject_absolute_path(parameter_name: str, tool_name: str, value: str) -> None:
    """Reject an absolute 'files/...' URL for tools that only accept home-relative paths."""
    if value.startswith("files/"):
        raise InvalidToolCallParameterException(
            parameter_name,
            f"{tool_name} requires a relative path under agent_home_dir; "
            "do not pass an absolute files/... URL",
        )


def relative_to(url: str, folder_url: str) -> str:
    """Path of `url` relative to the search root `folder_url` (used for glob matching)."""
    if url.startswith(folder_url):
        return url[len(folder_url) :]
    return url


def format_size(size: int | None) -> str:
    if size is None:
        return "-"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def code_block(text: str) -> str:
    """Wrap text in a fenced code block.

    The agent's tool results are rendered as markdown, which collapses single
    newlines into spaces. Fencing preserves line breaks and column alignment.
    """
    return f"```\n{text}\n```"


def render_listing(entries: list[tuple[str, FolderEntry]]) -> str:
    if not entries:
        return "(empty folder)"
    name_w = max(len(display) for display, _ in entries)
    name_w = max(name_w, len("NAME"))
    header = f"{'NAME':<{name_w}}  SIZE"
    rows = [header]
    for display, entry in entries:
        size_col = "-" if entry.is_folder else format_size(entry.size)
        rows.append(f"{display:<{name_w}}  {size_col}")
    return code_block("\n".join(rows))
