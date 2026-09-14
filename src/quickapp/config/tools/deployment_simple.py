from typing import Annotated, Literal

from pydantic import BaseModel, Field

from quickapp.common.base_config import DialResourceConfigField, PreviewField
from quickapp.config.tools.deployment import ConversationMode


class DialDeploymentSimpleTool(BaseModel):
    deployment_id: Annotated[str, DialResourceConfigField(description="The id of the deployment")]
    enabled: bool = Field(default=True, description="Whether the tool is enabled.")
    conversation_mode: ConversationMode | None = Field(
        default=None,
        description="Conversation session behavior for the DIAL deployment tool.",
    )
    propagate_annotations_to_choice: bool | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description=(
            "Propagate citation annotations returned by the deployment "
            "(`choices[].delta.custom_fields.annotations`) onto the app's choice. "
            "The orchestrator is instructed to copy the matching `<cit id=\"...\">` "
            "anchors verbatim; annotations whose anchor did not survive into the final "
            "answer are dropped."
        ),
    )
    type: Literal["dial-deployment-simple"] = Field(default="dial-deployment-simple")
