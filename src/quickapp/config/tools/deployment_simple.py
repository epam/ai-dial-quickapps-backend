from typing import Annotated, Literal

from pydantic import BaseModel, Field

from quickapp.common.base_config import DialResourceConfigField
from quickapp.config.tools.deployment import ConversationMode


class DialDeploymentSimpleTool(BaseModel):
    deployment_id: Annotated[str, DialResourceConfigField(description="The id of the deployment")]
    enabled: bool = Field(default=True, description="Whether the tool is enabled.")
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
    propagate_form_schema_to_choice: bool | None = Field(
        default=None,
        description=(
            "Propagate the form returned by the deployment onto the app's choice. "
            "The deployment's `custom_content.form_schema` is sent to the client. "
            "Within one deployment stream the last schema wins; across tools in one "
            "response the first one wins (the SDK allows a single form per choice)."
        ),
    )
    propagate_form_value_to_content: bool | None = Field(
        default=None,
        description=(
            "When the form's source tool is not resumable, append the submitted "
            "`custom_content.form_value` to the message content as a `<form_value>` block "
            "so the orchestrator model can use it. When false or unset, the value is only "
            "kept in `custom_content` (consumed by deployment tools)."
        ),
    )
    type: Literal["dial-deployment-simple"] = Field(default="dial-deployment-simple")
