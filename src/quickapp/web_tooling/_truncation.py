"""Truncation notice for oversized inline web fetches.

Shared by the tool (composes ``notice + blank line + head``) and the stage
wrapper (splits the notice back off to render it outside the verbatim block).
"""

# Tool-neutral (which tools can process a saved file varies per app) and embeds
# only values known before the head is cut, so its exact length can be reserved
# from the head budget.
TRUNCATION_NOTICE_TEMPLATE = (
    "[Truncated: fetched content is {total} bytes ({content_type}), larger "
    "than the inline cap; only the beginning follows. To process the full "
    "content, re-call with a save_path to persist it to the workspace, then "
    "use your available tools on it.]"
)

_NOTICE_PREFIX = "[Truncated: "
_SEPARATOR = "\n\n"


def compose_truncated_content(notice: str, head: str) -> str:
    return f"{notice}{_SEPARATOR}{head}"


def separator_byte_length() -> int:
    return len(_SEPARATOR.encode("utf-8"))


def split_truncation_notice(content: str) -> tuple[str | None, str]:
    """Split ``content`` into ``(notice, fetched text)``.

    Returns ``(None, content)`` for non-truncated results. Only a notice at
    position zero composed by :func:`compose_truncated_content` is split off, so
    fetched text cannot spoof its way out of the verbatim block.
    """
    if content.startswith(_NOTICE_PREFIX):
        notice, sep, body = content.partition(_SEPARATOR)
        if sep:
            return notice, body
    return None, content
