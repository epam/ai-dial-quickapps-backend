import logging

from pydantic import BaseModel, Field

from quickapp.agent.agent_settings import AgentSettings
from quickapp.common.base_config import BaseApplicationTypeConfig
from quickapp.config.context import Context
from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.prompt import AgentSystemPromptConfig
from quickapp.config.starters import ConversationStartersConfig
from quickapp.config.toolsets.toolset import ToolSet

logger = logging.getLogger(__name__)


def get_max_iterations() -> int:
    return AgentSettings().default_agent_max_iterations


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
    propagate_stages: bool = Field(
        default=True,
        description="When True (default), orchestrator model stages (reasoning steps) are shown on the choice. Set to False to hide them.",
    )


class ApplicationConfig(BaseApplicationTypeConfig):
    _dial_schema_id = "quickapps2"
    _dial_application_type_display_name = "Quick App 2.0"
    _dial_append_application_properties_header = False

    orchestrator: OrchestratorConfig = Field(description="The configuration for the orchestrator.")
    contexts: list[Context] = Field(description="The list of contexts.")
    tool_sets: list[ToolSet] = Field(description="The list of tool sets.")
    starters: list[str] | None = Field(
        description="**Deprecated, use conversation_starters**. The list of starters, which can be used to start the conversation with the agent.",
        default=None,
        deprecated="This field is deprecated and will be removed in future versions. Please use 'conversation_starters' instead.",
    )
    conversation_starters: ConversationStartersConfig | None = Field(
        description="The configuration for conversation starters.", default=None
    )
