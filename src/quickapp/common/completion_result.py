from typing import Any, Optional

from aidial_client.types.chat.response import Attachment
from aidial_sdk.chat_completion.request import CustomContent, Message, Role
from pydantic import BaseModel, Field

from quickapp.common.deployment_usage import DeploymentUsage


class CompletionResult(BaseModel):
    tool_call_id: Optional[str] = None
    content: Any
    content_type: str
    attachments: Optional[list[Attachment]] = None
    usage: Optional[list[DeploymentUsage]] = None

    propagate_to_choice: list[Attachment] = Field(default_factory=list)

    def to_tool_message(self):
        if not self.tool_call_id:
            raise RuntimeError("Tool call result doesn't contain tool_call id")

        return Message(
            role=Role.TOOL,
            content=self.content,
            custom_content=CustomContent(
                attachments=self.attachments,
                # state={"usage": self.deployment_usage}
            ),
            tool_call_id=self.tool_call_id,
        )
