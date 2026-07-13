"""Truncation notice for oversized inline web fetches.

Shared by the tool (which composes ``notice + blank line + fetched head``) and
the stage wrapper (which splits the notice back off to render it outside the
verbatim content block). Keeping the format here is what lets the wrapper
separate the tool's instructions from the fetched text without guessing.
"""

# Deliberately tool-neutral: which tools can process a saved file varies per
# app (file tools, RAG, get_content, ...), and this module must not assume any
# of them is enabled. Embeds only values known before the head is cut (total
# size, content type) so the notice can be rendered once, up front, and its
# exact length reserved from the head budget.
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

    Returns ``(None, content)`` unchanged for non-truncated results. Only a
    notice composed by :func:`compose_truncated_content` is split off — it sits
    at position zero, before any fetched byte, so fetched text can never spoof
    its way out of the verbatim block.
    """
    if content.startswith(_NOTICE_PREFIX):
        notice, sep, body = content.partition(_SEPARATOR)
        if sep:
            return notice, body
    return None, content
