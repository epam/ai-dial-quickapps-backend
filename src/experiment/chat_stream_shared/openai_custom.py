"""Mirror of quickapp.agent._stage_delta_types attachment helpers (sandbox only; drop when merged)."""

from typing import Any


def attachment_kwargs(att: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": att.get("type"),
        "title": att.get("title"),
        "data": att.get("data"),
        "url": att.get("url"),
        "reference_url": att.get("reference_url"),
        "reference_type": att.get("reference_type"),
    }


def normalize_attachment(attachment: dict[str, Any]) -> None:
    if attachment.get("data") is None and attachment.get("url") is None:
        if attachment.get("reference_url") is None:
            attachment["data"] = ""
        else:
            attachment["url"] = attachment.get("reference_url")
