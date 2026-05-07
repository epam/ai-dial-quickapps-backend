from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency


class HookEvent(StrEnum):
    ON_REQUEST_START = "on_request_start"
    ON_PRE_LLM = "on_pre_llm"
    ON_PRE_TOOL_USE = "on_pre_tool_use"
    ON_POST_TOOL_USE = "on_post_tool_use"
    ON_ITERATION_END = "on_iteration_end"
    ON_COMPLETION = "on_completion"


class _BaseHookConfig(BaseModel):
    event: HookEvent
    name: str | None = None


class ToolCallHookConfig(_BaseHookConfig):
    kind: Literal["tool_call"] = "tool_call"
    toolset_name: str | None = None
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    frequency: InjectionFrequency = InjectionFrequency.APPEND_IF_CHANGED


# Single-variant discriminated union — add new variants here as
# Annotated[Union[ToolCallHookConfig, NextHookConfig], Field(discriminator="kind")]
HookConfig = ToolCallHookConfig
