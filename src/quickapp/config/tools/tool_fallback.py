import logging
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class TriggerOnType(StrEnum):
    contains = "contains"
    equals = "equals"


class TriggerOn(BaseModel):
    type: TriggerOnType = Field(description="The type of the trigger on condition.")
    value: str = Field(description="The value to match against.")
    case_sensitive: bool = Field(
        default=False,
    )


class BaseToolFallbackStrategyModel(BaseModel):
    trigger_on: TriggerOn | None = Field(
        default=None,
        description="The trigger on condition. If set as `null`, it will be applied to all tool errors.",
    )


class StopStrategyModel(BaseToolFallbackStrategyModel):
    type: Literal["stop"] = Field(default="stop", description="The type of the strategy.")


class BaseHandleStrategyModel(BaseToolFallbackStrategyModel):
    instructions: str | None = Field(
        default=None,
        description=(
            "Instructions appended to the forwarded error when trigger_on is set. "
            "Ignored on catch-all strategies (no trigger_on)."
        ),
    )
    forward_tool_error_message: bool = Field(
        default=False,
        deprecated=(
            "forward_tool_error_message is deprecated and has no effect. "
            "Tool error messages are now always forwarded to the LLM."
        ),
        description=(
            "Deprecated: no longer has any effect. "
            "Tool error messages are now always forwarded to the LLM."
        ),
    )

    @model_validator(mode="after")
    def _warn_deprecated_forward_flag(self) -> "BaseHandleStrategyModel":
        if self.forward_tool_error_message:
            logger.warning(
                "forward_tool_error_message=True is set but has no effect; "
                "tool error messages are now always forwarded to the LLM regardless of this setting."
            )
        return self


class ContinueStrategyModel(BaseHandleStrategyModel):
    type: Literal["continue"] = Field(default="continue", description="The type of the strategy.")


class RetryStrategyModel(BaseHandleStrategyModel):
    type: Literal["retry"] = Field(
        default="retry",
        deprecated=(
            "Strategy type 'retry' is deprecated. Use type 'continue' instead. "
            "The instructions field remains effective for triggered strategies."
        ),
        description="Deprecated: use type 'continue' instead.",
    )
    instructions: str = Field(
        ...,
        description="Instructions to LLM what to do next.",
    )

    @model_validator(mode="after")
    def _warn_deprecated_retry(self) -> "RetryStrategyModel":
        logger.warning(
            "Strategy type 'retry' is deprecated and will be removed in the next major release. "
            "Use type 'continue' instead."
        )
        return self


ToolFallbackStrategyModel = Annotated[
    StopStrategyModel | ContinueStrategyModel | RetryStrategyModel,
    Field(discriminator="type"),
]


class ToolFallbackConfig(BaseModel):
    strategies: list[ToolFallbackStrategyModel] = Field(
        default_factory=lambda: [ContinueStrategyModel()],  # type: ignore[arg-type]
        description="Strategy to handle tool fallbacks.",
    )
    display_error_in_stage: bool = Field(
        default=True,
        description="Whether to display exception message in the stage or just error notification.",
    )
