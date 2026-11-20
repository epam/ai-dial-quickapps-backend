from typing import Any

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from pydantic import BaseModel, Field

from quickapp.common.deployment_usage import DeploymentUsage

IS_ERROR_STATE_KEY = "is_error"


class ToolCallResult(BaseModel):
    tool_call_id: str | None = None
    content: str
    content_type: str
    attachments: list[Attachment] | None = None
    state: dict[str, Any] | None = None
    usage: list[DeploymentUsage] | None = None

    propagate_to_choice: list[Attachment] = Field(default_factory=list)
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    is_error: bool = False
    form_schema: dict[str, Any] | None = None

    def to_tool_message(self):
        if not self.tool_call_id:
            raise RuntimeError("Tool call result doesn't contain tool_call id")

        state = self.state
        if self.is_error:
            # Persisted in tool_execution_history so failed calls can be told apart reliably.
            state = {**(state or {}), IS_ERROR_STATE_KEY: True}

        return Message(
            role=Role.TOOL,
            content=self.content,
            custom_content=CustomContent(
                attachments=self.attachments,
                state=state,
                form_schema=self.form_schema,
            ),
            tool_call_id=self.tool_call_id,
        )


def _infer_content_type_from_tool_body(content: str) -> str:
    stripped = content.lstrip()
    if stripped[:1] in "{[":
        return "application/json"
    return "text/plain"


def tool_call_result_from_tool_message(msg: Message) -> ToolCallResult:
    """Build a ToolCallResult mirroring a TOOL message (for deferred stage UI after recovery)."""
    raw = msg.content
    content = "" if raw is None else (raw if isinstance(raw, str) else str(raw))
    attachments_list: list[Attachment] | None = None
    state = None
    form_schema = None
    if msg.custom_content is not None:
        attachments_list = msg.custom_content.attachments
        state = msg.custom_content.state
        form_schema = msg.custom_content.form_schema
    is_error = bool(state and state.get(IS_ERROR_STATE_KEY) is True)
    attachments_out: list[Attachment] = [] if attachments_list is None else attachments_list
    return ToolCallResult(
        content=content,
        content_type=_infer_content_type_from_tool_body(content),
        attachments=attachments_out,
        state=state,
        is_error=is_error,
        form_schema=form_schema if isinstance(form_schema, dict) else None,
    )
