from pydantic import BaseModel, Field


class ToolStageConfig(BaseModel):
    name: str | None = Field(
        default=None,
        description="The name of the tool stage. Can contain placeholders for tool arguments in curly braces.",
    )
    body: str | None = Field(
        default=None,
        description="The body of the tool stage. Can contain placeholders for tool arguments in curly braces.",
    )
    show: bool = Field(
        default=True,
        description="Whether the tool stage should be shown in the chat.",
    )
    defer_close: bool = Field(
        default=False,
        description=(
            "When True, the stage stays open until parallel tool execution finishes "
            "rather than closing when this tool returns. Useful when a later "
            "recovery step may rewrite the tool's result."
        ),
    )


class ToolDisplayConfig(BaseModel):
    stage: ToolStageConfig | None = Field(
        default=None,
        description="The configuration for the tool stage.",
    )
