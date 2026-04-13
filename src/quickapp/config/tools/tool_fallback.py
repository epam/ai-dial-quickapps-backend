from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


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
        description="Instructions to LLM what to do next.",
    )


class ContinueStrategyModel(BaseHandleStrategyModel):
    type: Literal["continue"] = Field(default="continue", description="The type of the strategy.")

    @model_validator(mode="after")
    def _require_instructions_with_trigger(self) -> "ContinueStrategyModel":
        if self.trigger_on is not None and self.instructions is None:
            raise ValueError(
                "ContinueStrategyModel with `trigger_on` set must also provide "
                "`instructions`. Otherwise the generic fallback text would silently "
                "replace any built-in handling."
            )
        return self


class RetryStrategyModel(BaseHandleStrategyModel):
    type: Literal["retry"] = Field(default="retry", description="The type of the strategy.")
    instructions: str = Field(
        ...,
        description="Instructions to LLM what to do next. Must be provided for retry strategy.",
    )


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
