from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class HookToolCall(_FrozenModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class HookMessage(_FrozenModel):
    role: str
    content: str | None = None
    tool_calls: list[HookToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class HookContext(_FrozenModel):
    """Read-only snapshot of the conversation handed to a hook."""

    event: str
    messages: list[HookMessage]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def last_user_message(self) -> HookMessage | None:
        for message in reversed(self.messages):
            if message.role == "user":
                return message
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def last_assistant_message(self) -> HookMessage | None:
        """The last assistant message that is a final answer (carries no tool calls)."""
        for message in reversed(self.messages):
            if message.role == "assistant" and not message.tool_calls:
                return message
        return None


class RequestStartHookContext(HookContext):
    pass


class CompletionHookContext(HookContext):
    iteration_count: int
    total_tool_calls: int


class HookResult(_FrozenModel):
    """Outcome of one hook run. ``arguments`` are the arguments actually used."""

    hook_name: str
    content: str | None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
