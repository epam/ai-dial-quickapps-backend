"""DI-free helpers shared by the DIAL file tools: path math and listing rendering.

These have no dependency on `self`/DI, so they live here rather than on the
`_DialFileTool` base class (which holds the download/resolution behaviour).
"""

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_names import INTERNAL_FILE_READ_CHARS_TOOL_NAME
from quickapp.common.utils import fenced_code_block
from quickapp.dial_core_services.dial_file_service import FolderEntry

# Read-back tools (read_lines, read_chars, search) are excluded from offload, so an
# oversized result cannot be re-saved to a file and would go straight into the LLM
# context. These caps bound that context cost instead. 8_000 chars is at most
# 32_000 UTF-8 bytes (4 bytes/char worst case), i.e. also under the default
# 40_000-byte offload threshold, so a result never looks "oversized" by that measure.
MAX_OUTPUT_CHARS = 8_000
MAX_LINE_CHARS = 2_000


def truncate_line(line: str) -> str:
    """Cut an overlong line to ``MAX_LINE_CHARS`` and point the model at read_chars."""
    if len(line) <= MAX_LINE_CHARS:
        return line
    omitted = len(line) - MAX_LINE_CHARS
    return (
        f"{line[:MAX_LINE_CHARS]}... [line truncated: {omitted} more characters; "
        f"use {INTERNAL_FILE_READ_CHARS_TOOL_NAME} to read the rest]"
    )


def cap_output(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    """Limit ``text`` to ``limit`` chars, cutting on a line boundary when possible.

    Returns the (possibly shortened) text and whether anything was dropped.
    """
    if len(text) <= limit:
        return text, False
    cut = text.rfind("\n", 0, limit + 1)
    if cut <= 0:
        cut = limit
    return text[:cut], True


def is_root_reference(path: str) -> bool:
    """Whether the path denotes the agent home directory itself ('', '.', './', '/')."""
    return path.strip() in ("", ".", "./", "/")


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
    return fenced_code_block("\n".join(rows))
