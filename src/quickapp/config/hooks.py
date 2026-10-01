from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from quickapp.common.hook_context.context import (
    CompletionHookContext,
    HookContext,
    RequestStartHookContext,
)
from quickapp.common.hook_context.templating import contains_placeholder, validate_template_paths
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency


class HookEvent(StrEnum):
    ON_REQUEST_START = "on_request_start"
    ON_COMPLETION = "on_completion"
    # ON_PRE_LLM = "on_pre_llm"
    # ON_PRE_TOOL_USE = "on_pre_tool_use"
    # ON_POST_TOOL_USE = "on_post_tool_use"
    # ON_ITERATION_END = "on_iteration_end"


# Context model each event hands to its hooks; argument templates are validated against it.
_EVENT_CONTEXT_MODELS: dict[HookEvent, type[HookContext]] = {
    HookEvent.ON_REQUEST_START: RequestStartHookContext,
    HookEvent.ON_COMPLETION: CompletionHookContext,
}


class TTLRefreshCondition(BaseModel):
    kind: Literal["ttl"] = "ttl"
    ttl_minutes: int = Field(gt=0)


# Single-variant — add new variants here as
# Annotated[Union[TTLRefreshCondition, NextCondition], Field(discriminator="kind")]
RefreshConditionConfig = TTLRefreshCondition


class _BaseHookConfig(BaseModel):
    event: HookEvent
    name: str | None = None
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Maximum run time of one hook invocation, in seconds. When exceeded the hook is "
            "cancelled and skipped. Defaults per event: unlimited for 'on_request_start', "
            "30 for 'on_completion'."
        ),
    )


class ToolCallHookConfig(_BaseHookConfig):
    kind: Literal["tool_call"] = "tool_call"
    toolset_name: str | None = None
    tool_name: str
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arguments forwarded to the tool. String values may contain '${path}' placeholders "
            "resolved from the hook context (for example '${last_user_message.content}'); a string "
            "that is exactly one placeholder keeps the value's JSON type. Use '\\${' for a literal "
            "'${'. Paths are validated when the manifest is loaded."
        ),
    )
    frequency: InjectionFrequency = InjectionFrequency.APPEND_IF_CHANGED
    refresh_condition: RefreshConditionConfig | None = None

    @model_validator(mode="after")
    def _reject_request_start_only_fields(self) -> Self:
        if self.event is HookEvent.ON_COMPLETION:
            for field_name in ("frequency", "refresh_condition"):
                if field_name in self.model_fields_set:
                    raise ValueError(
                        f"'{field_name}' is only supported for event 'on_request_start'"
                    )
        return self

    @model_validator(mode="after")
    def _validate_argument_templates(self) -> Self:
        validate_template_paths(self.arguments, _EVENT_CONTEXT_MODELS[self.event])
        if self.refresh_condition is not None and contains_placeholder(self.arguments):
            raise ValueError(
                "'refresh_condition' cannot be combined with '${...}' placeholders in 'arguments'"
            )
        return self


# Single-variant discriminated union — add new variants here as
# Annotated[Union[ToolCallHookConfig, NextHookConfig], Field(discriminator="kind")]
HookConfig = ToolCallHookConfig
