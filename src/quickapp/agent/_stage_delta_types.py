"""Types for DIAL custom_content.stages (root and subagent streams).

Same logical shape for both: list of stage delta objects keyed by index (0-based).
When index is missing, position in the list is used as fallback.

Stream yields raw dicts; convert at the boundary with as_stage_delta() then use StageDeltaItem everywhere.
"""

from typing import Any, TypedDict, cast


class StageDeltaItem(TypedDict, total=False):
    """One item from delta.custom_content.stages. All fields optional (incremental)."""

    index: int
    name: str
    content: str
    attachments: list[dict[str, Any]]
    status: str


def as_stage_delta(item: dict[str, Any]) -> StageDeltaItem:
    """Convert a stream dict to StageDeltaItem. Call at the boundary only.
    No structural validation; caller must only pass trusted stream dicts."""
    return cast(StageDeltaItem, cast(object, item))


def get_stage_index(item: StageDeltaItem | dict[str, Any], position: int) -> int:
    """Resolve stage index from a delta item; use position as fallback."""
    if "index" in item and isinstance(item["index"], int):
        return int(item["index"])
    return position


def stage_display_name(item: StageDeltaItem, index: int) -> str:
    """Display name for a stage from delta item; fallback to 'Stage {index+1}'."""
    name = ""
    if "name" in item and item["name"] is not None:
        name = str(item["name"]).strip()
    return name or f"Stage {index + 1}"


def attachment_kwargs(att: dict[str, Any]) -> dict[str, Any]:
    """Kwargs for add_attachment() from an attachment dict. Keys in one place."""
    return {
        "type": att.get("type"),
        "title": att.get("title"),
        "data": att.get("data"),
        "url": att.get("url"),
        "reference_url": att.get("reference_url"),
        "reference_type": att.get("reference_type"),
    }


def normalize_attachment(attachment: dict[str, Any]) -> None:
    """Apply issue#16: if no data and no url, set data='' or url=reference_url. Mutates in place."""
    if attachment.get("data") is None and attachment.get("url") is None:
        if attachment.get("reference_url") is None:
            attachment["data"] = ""
        else:
            attachment["url"] = attachment.get("reference_url")
