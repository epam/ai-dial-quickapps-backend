from typing import Literal, Self

from pydantic import BaseModel, Field, PrivateAttr

from quickapp.config.dial_deployment import DialDeploymentToolConfig
from quickapp.config.prompt import ToolSystemPromptConfig
from quickapp.config.tools.base import BaseOpenAITool


class ConversationMode(BaseModel):
    resumable: bool = Field(
        default=False,
        description=(
            "Whether the deployment tool maintains a resumable conversation. When true, "
            "the tool issues a session_id on the first call, accepts it back on follow-up "
            "calls, and the backend threads prior [user, assistant] history — including the "
            "subagent's internal tool-execution state — for that session. When false "
            "(default), each call is independent."
        ),
    )


class ContentPropagation(BaseModel):
    propagate_history: bool = Field(
        default=False,
        deprecated=(
            "Deprecated and will be removed in a future release. "
            "Use 'conversation_mode.resumable: true' instead."
        ),
        description=(
            "**Deprecated, use `conversation_mode.resumable: true`**. "
            "Flag to propagate messages to deployment. If True, the messages will be "
            "propagated in such way: [assistant, tool] -> [user, assistant]."
        ),
    )
    propagate_headers: list[str] | None = Field(
        default=None,
        description="List of headers to propagate to the DIAL deployment. If None, the default headers will be used.",
    )


class DialDeploymentTool(BaseOpenAITool):
    type: Literal["deployment-tool"] = Field(default="deployment-tool")
    deployment: DialDeploymentToolConfig = Field(
        description="The configuration for the DIAL deployment tool."
    )
    system_prompt: ToolSystemPromptConfig | None = Field(
        default=None,
        description="The configuration for the system prompt used in the DIAL deployment tool.",
    )
    content_propagation: ContentPropagation | None = Field(
        default=None, description="The configuration with propagations to DIAL deployment."
    )
    conversation_mode: ConversationMode | None = Field(
        default=None,
        description="Conversation session behavior for the DIAL deployment tool.",
    )
    propagate_annotations_to_choice: bool | None = Field(
        default=None,
        description=(
            "Propagate citation annotations returned by the deployment "
            "(`choices[].delta.custom_fields.annotations`) onto the app's choice. "
            "Annotations are forwarded unchanged; the orchestrator is instructed to copy "
            "the matching `<cit data-id=\"...\"></cit>` anchors verbatim into its answer."
        ),
    )
    supports_url_attachments: bool = Field(
        default=False,
        description=(
            "Whether the underlying DIAL deployment advertises "
            "`features.url_attachments`. Snapshotted at tool-config build time. "
            "When true, external URLs are forwarded as `reference_url` attachments; "
            "when false, they are materialised into DIAL files first."
        ),
    )
    # Runtime-only, never read from a manifest: a tool synthesized from a DialAppToolSet has no
    # owning DeploymentToolSet, so the headers resolved for that toolset travel on the tool.
    _forwarded_headers: dict[str, str] | None = PrivateAttr(default=None)

    @property
    def forwarded_headers(self) -> dict[str, str] | None:
        return self._forwarded_headers

    def with_forwarded_headers(self, headers: dict[str, str] | None) -> Self:
        copy = self.model_copy()
        copy._forwarded_headers = headers
        return copy
