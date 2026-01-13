import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

from quickapp.common.base_config import BaseApplicationTypeConfig
from quickapp.config.context import Context
from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.prompt import AgentSystemPromptConfig
from quickapp.config.toolsets.toolset import ToolSet

logger = logging.getLogger(__name__)


def get_max_iterations() -> int:
    return int(os.getenv("DEFAULT_AGENT_MAX_ITERATIONS", "15"))


class OrchestratorConfig(BaseModel):
    deployment: DialDeploymentConfig = Field(
        description="The configuration for the orchestrator DIAL deployment."
    )
    system_prompt: AgentSystemPromptConfig = Field(
        description="The configuration for the system prompt."
    )
    max_iterations: int = Field(
        default_factory=get_max_iterations,
        description="The max count of orchestrator(agent) operations. Default: 15",
    )


class ApplicationConfig(BaseApplicationTypeConfig):
    _dial_schema_id = "quickapps2"
    _dial_application_type_display_name = "Quick App 2.0"
    _dial_append_application_properties_header = False

    orchestrator: OrchestratorConfig = Field(description="The configuration for the orchestrator.")
    contexts: list[Context] = Field(description="The list of contexts.")
    tool_sets: list[ToolSet] = Field(description="The list of tool sets.")
    starters: Optional[list[str]] = Field(description="The list of starter buttons.", default=None)
