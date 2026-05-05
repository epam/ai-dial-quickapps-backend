from typing import Any

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from pydantic import BaseModel, Field

from quickapp.common.deployment_usage import DeploymentUsage


class ToolCallResult(BaseModel):
    tool_call_id: str | None = None
    content: str
    content_type: str
    attachments: list[Attachment] | None = None
    state: dict[str, Any] | None = None
    usage: list[DeploymentUsage] | None = None

    propagate_to_choice: list[Attachment] = Field(default_factory=list)

    def to_tool_message(self):
        if not self.tool_call_id:
            raise RuntimeError("Tool call result doesn't contain tool_call id")

        return Message(
            role=Role.TOOL,
            content=self.content,
            custom_content=CustomContent(
                attachments=self.attachments,
                state=self.state,
            ),
            tool_call_id=self.tool_call_id,
        )
