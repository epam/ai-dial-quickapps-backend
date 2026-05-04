import logging

from pydantic import BaseModel, Field, model_validator

from quickapp.agent.agent_settings import AgentSettings
from quickapp.common.base_config import BaseApplicationTypeConfig, PreviewField, has_preview_marker
from quickapp.common.feature_settings import FeatureSettings
from quickapp.config.context import Context
from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.prompt import AgentSystemPromptConfig
from quickapp.config.skill import SkillConfig
from quickapp.config.starters import ConversationStartersConfig
from quickapp.config.timestamp import TimestampConfig, ToolCallTimestampConfig
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


def nullify_preview_fields(model: BaseModel) -> None:
    """Recursively nullify preview fields on a config model tree.

    Recurses into nested BaseModel instances but not into lists or dicts —
    preview fields are expected on config objects, not inside collections.
    """
    for field_name, field_info in type(model).model_fields.items():
        value = getattr(model, field_name)
        if has_preview_marker(field_info) and value is not None:
            setattr(model, field_name, None)
            logger.warning(
                'Preview feature "%s" is configured but preview features are disabled '
                "(ENABLE_PREVIEW_FEATURES is not set). The feature has been deactivated.",
                field_name,
            )
        elif isinstance(value, BaseModel):
            nullify_preview_fields(value)


class Features(BaseModel):
    timestamp: TimestampConfig | None = PreviewField(  # type: ignore[assignment]
        default_factory=ToolCallTimestampConfig,
        description="Time awareness configuration.",
    )


class ToolDefaults(BaseModel):
    """Defaults applied to every tool call unless overridden locally.

    Container (rather than a bare field on `ApplicationConfig`) so future
    tool-wide defaults can land as sibling fields without a breaking schema
    change.
    """

    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        le=3600,
        description=(
            "Timeout (in seconds) applied to all tool calls in this app. "
            "When unset, the env default `DEFAULT_TOOL_TIMEOUT_SECONDS` is used, "
            "or each client's library default if neither is set."
        ),
    )
    max_file_download_bytes: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Maximum size (in bytes) of a single file the agent will download "
            "from DIAL Core when resolving file arguments for a tool call. "
            "When unset, the env default `DIAL_FILE_MAX_DOWNLOAD_BYTES` is used "
        ),
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
    skills: list[SkillConfig] | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description="Optional list of user-configured agent skills.",
    )
    features: Features | None = Field(
        default_factory=Features,
        description="QuickApps Agent features configuration.",
    )
    tool_defaults: ToolDefaults = Field(
        default_factory=ToolDefaults,
        description="Defaults applied to every tool call (e.g. timeout).",
    )

    @model_validator(mode="after")
    def _gate_preview_fields(self) -> "ApplicationConfig":
        if FeatureSettings().enable_preview_features:
            return self
        nullify_preview_fields(self)
        return self
