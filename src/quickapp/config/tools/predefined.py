from typing import Any, Literal

from pydantic import BaseModel, Field


class PredefinedTool(BaseModel):
    """Represents a reference to a single tool template."""

    type: Literal["predefined-tool"] = Field(
        default="predefined-tool",
        description="The type indicating this is a tool template reference.",
    )
    template_name: str = Field(
        description="The name of the tool template file (without extension), e.g., 'rag_tool'."
    )
    enabled: bool = Field(default=True, description="Whether the tool is enabled.")
    override: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional JSON Merge Patch (RFC 7396) applied to the resolved tool template before "
            "validation. May not target the `type` discriminator at any depth."
        ),
    )
