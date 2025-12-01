from typing import Literal

from pydantic import BaseModel, Field

from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.prompt import ToolSystemPromptConfig
from quickapp.config.tools.base import BaseOpenAITool


class ContentPropagation(BaseModel):
    propagate_history: bool = Field(
        default=False,
        description="Flag to propagate messages to deployment. If True, the messages will be propagated in such way: [assistant, tool] -> [user, assistant].",
    )
    propagate_headers: list[str] | None = Field(
        default=None,
        description="List of headers to propagate to the DIAL deployment. If None, the default headers will be used.",
    )


class DialDeploymentTool(BaseOpenAITool):
    type: Literal["deployment-tool"] = Field(default="deployment-tool")
    deployment: DialDeploymentConfig = Field(
        description="The configuration for the DIAL deployment tool."
    )
    system_prompt: ToolSystemPromptConfig | None = Field(
        default=None,
        description="The configuration for the system prompt used in the DIAL deployment tool.",
    )
    content_propagation: ContentPropagation | None = Field(
        default=None, description="The configuration with propagations to DIAL deployment."
    )
