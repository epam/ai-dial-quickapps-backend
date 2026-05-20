import logging

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


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
        deprecated="use stage_level=StageDisplayLevel.DEBUG at the call site instead.",
    )
    defer_close: bool = Field(
        default=False,
        description=(
            "When True, the stage stays open until parallel tool execution finishes "
            "rather than closing when this tool returns. Useful when a later "
            "recovery step may rewrite the tool's result."
        ),
    )

    @model_validator(mode="after")
    def _warn_if_show_false(self) -> "ToolStageConfig":
        if not self.show:
            logger.warning(
                "display.stage.show=false is deprecated and will be removed in a future version."
            )
        return self


class ToolDisplayConfig(BaseModel):
    stage: ToolStageConfig | None = Field(
        default=None,
        description="The configuration for the tool stage.",
    )
