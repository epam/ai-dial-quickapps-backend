from typing import Any, Literal

from pydantic import BaseModel, Field


class PredefinedToolSet(BaseModel):
    type: Literal["predefined"] = Field(
        default="predefined", description="The type of the tool set."
    )
    template_name: str = Field(description="Name of the predefined template")
    override: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional JSON Merge Patch (RFC 7396) applied to the resolved toolset template "
            "before validation. May not target the `type` discriminator at any depth."
        ),
    )
