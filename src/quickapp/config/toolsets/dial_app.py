from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from quickapp.common.base_config import DialResourceConfigField, PreviewField
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.deployment import ConversationMode
from quickapp.config.tools.tool_fallback import ToolFallbackConfig
from quickapp.config.toolsets.base import BaseToolSet
from quickapp.config.toolsets.hidden_from_model import (
    HIDDEN_FROM_MODEL_DESCRIPTION,
    validate_hidden_from_model,
)


class DialAppToolSet(BaseToolSet):
    type: Literal["dial-app"] = Field(default="dial-app", description="The type of the tool set.")
    deployment_id: Annotated[
        str,
        DialResourceConfigField(description="The DIAL deployment or application id."),
    ]
    transport: Literal["auto", "mcp", "chat-completion"] = Field(
        default="auto",
        description=(
            "Routing override. 'auto' (default): use MCP if the deployment advertises "
            "features.mcp, otherwise chat completion. 'mcp': force MCP — initialization "
            "fails with a ToolInitializationException if features.mcp is not advertised. "
            "'chat-completion': force chat completion — the resolver skips the metadata "
            "fetch and goes directly to get_basic_tool_config."
        ),
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        description=(
            "MCP branch only: whitelist the subset of MCP tool names that reach the agent. "
            "Ignored (with a warning) on the chat-completion fallback branch."
        ),
    )
    hidden_from_model: list[str] | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description=(
            f"MCP branch only. {HIDDEN_FROM_MODEL_DESCRIPTION} "
            "Ignored (with a warning) on the chat-completion fallback branch."
        ),
    )
    attachment: AttachmentConfig = Field(
        default_factory=AttachmentConfig, description="Configuration for toolset attachments."
    )
    fallback_configuration: ToolFallbackConfig = Field(
        default_factory=ToolFallbackConfig, description="Tool fallback configuration."
    )
    conversation_mode: ConversationMode | None = Field(
        default=None,
        description=(
            "Conversation session behavior for the DIAL deployment tool. Applies only on "
            "the chat-completion branch; ignored (with a warning) when the toolset resolves "
            "to MCP."
        ),
    )

    @model_validator(mode="after")
    def _validate_hidden_from_model(self) -> Self:
        validate_hidden_from_model(self.allowed_tools, self.hidden_from_model)
        return self
