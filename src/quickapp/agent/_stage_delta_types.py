"""Types for DIAL custom_content.stages (root and subagent streams).

Same logical shape for both: list of stage delta objects keyed by index (0-based).
When index is missing, position in the list is used as fallback.
"""

from typing import Any, TypedDict


class StageDeltaItem(TypedDict, total=False):
    """One item from delta.custom_content.stages. All fields optional (incremental)."""

    index: int
    name: str
    title: str
    content: str
    attachments: list[dict[str, Any]]
    status: str


def get_stage_index(item: dict[str, Any], position: int) -> int:
    """Resolve stage index from a delta item; use position as fallback."""
    if "index" in item and isinstance(item["index"], int):
        return int(item["index"])
    return position


