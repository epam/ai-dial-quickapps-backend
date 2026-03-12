"""Data contracts for subagent stage propagation from deployment completion stream.

Assumed shape of delta.custom_content.stages in the DIAL chat completion stream.
Each item may be sent incrementally (e.g. per-stage deltas) or as a full list;
fields are optional to support partial payloads.
"""

from typing import Any

from pydantic import BaseModel, Field


def parse_stages(raw_stages: Any) -> list["SubagentStageDelta"]:
    """Parse raw delta.custom_content.stages into a list of SubagentStageDelta.

    Resilient to partial or malformed payloads: only valid list items are
    returned; non-dict items and parse failures are skipped.
    """
    if not isinstance(raw_stages, list):
        return []
    result: list[SubagentStageDelta] = []
    for item in raw_stages:
        if not isinstance(item, dict):
            continue
        try:
            result.append(SubagentStageDelta.model_validate(item))
        except Exception:
            continue
    return result


class SubagentStageDelta(BaseModel):
    """One stage-like object in delta.custom_content.stages from a subagent stream.

    Stages are identified by index. Same index across deltas = same stage; merge
    name, content, attachments, status. New index = new stage.
    """

    index: int | None = Field(
        default=None,
        description="Stage index (0-based). Identifies which stage this delta updates.",
    )
    name: str | None = Field(
        default=None,
        description="Display name or name part (may be sent in chunks, e.g. title then ' [0.01s]').",
    )
    title: str | None = Field(
        default=None,
        description="Alternative to name for stage display (e.g. from DIAL API).",
    )
    content: str | None = Field(
        default=None,
        description="Stage body content; may be sent in chunks for streaming.",
    )
    attachments: list[Any] | None = Field(
        default=None,
        description="Optional attachments for this stage (shape depends on DIAL client).",
    )
    status: str | None = Field(
        default=None,
        description="Stage status (e.g. 'completed'). Last value received is kept.",
    )

    def name_part(self) -> str:
        """Return name or title for this delta (to append to accumulated name)."""
        return (self.name or self.title or "").strip()
