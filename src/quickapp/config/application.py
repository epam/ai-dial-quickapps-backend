import logging
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.fields import FieldInfo

from quickapp.agent.agent_settings import AgentSettings
from quickapp.common.base_config import BaseApplicationTypeConfig, PreviewField, has_preview_marker
from quickapp.common.feature_settings import FeatureSettings
from quickapp.config.context import Context
from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.dial_files import DialFilesConfig
from quickapp.config.hooks import HookConfig
from quickapp.config.orchestrator_attachment_strategy import LazyOnDemandAttachmentStrategy
from quickapp.config.prompt import AgentSystemPromptConfig
from quickapp.config.skill import SkillConfig
from quickapp.config.starters import ConversationStartersConfig
from quickapp.config.timestamp import TimestampConfig, ToolCallTimestampConfig
from quickapp.config.toolsets.toolset import ToolSet

logger = logging.getLogger(__name__)


class StageDisplayLevel(str, Enum):
    ERROR = "error"
    INFO = "info"
    DEBUG = "debug"


class StageDisplayConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: StageDisplayLevel = Field(
        default=StageDisplayLevel.INFO,
        description="Threshold for stage visibility. errors=failures only; info=user-facing (default); debug=all.",
    )


def get_max_iterations() -> int:
    return AgentSettings().default_agent_max_iterations


def _orchestrator_deployment_field() -> FieldInfo:
    description = "The configuration for the orchestrator DIAL deployment."
    env_id = AgentSettings().default_orchestrator_deployment_id
    if env_id is None:
        return Field(description=description)
    # `default_factory` produces a fresh instance per validation; `json_schema_extra`
    # injects the minimal `{"deployment_id": ...}` default into the JSON schema so DIAL
    # Core's manifest UI can pre-fill the orchestrator field. Without the extra, pydantic
    # would auto-dump the whole DialDeploymentConfig instance (including nullable
    # parameters) into the schema's default.
    return Field(  # type: ignore[return-value]
        default_factory=lambda: DialDeploymentConfig(deployment_id=env_id),
        json_schema_extra={"default": {"deployment_id": env_id}},
        description=description,
    )


class OrchestratorConfig(BaseModel):
    deployment: DialDeploymentConfig = _orchestrator_deployment_field()  # type: ignore[assignment]
    system_prompt: AgentSystemPromptConfig = Field(
        description="The configuration for the system prompt."
    )
    max_iterations: int = Field(  # type: ignore[return-value]
        default_factory=get_max_iterations,
        json_schema_extra={"default": 15},
        description="The max count of orchestrator(agent) operations. Default: 15",
    )
    propagate_stages: bool = Field(
        default=True,
        description="When True (default), orchestrator model stages (reasoning steps) are shown on the choice. Set to False to hide them.",
    )
    attachment_strategy: LazyOnDemandAttachmentStrategy | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description=(
            "How the orchestrator receives request-scoped attachments. "
            "When unset, the orchestrator gets no admin/user attachments on the "
            "native path (legacy behaviour: USER `image/*` passes through, other "
            "MIMEs are surfaced as XML metadata only)."
        ),
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


class FileLoadingConfig(BaseModel):
    size_limit: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Maximum size (in bytes) of a single file the agent will download. "
            "When unset, the env default `DEFAULT_FILE_LOADING_SIZE_LIMIT` is used "
            "(default 10 MiB)."
        ),
    )


class ExternalUrlFetchConfig(BaseModel):
    enabled: bool | None = Field(
        default=None,
        description=(
            "Per-app override for fetching external (non-DIAL) URLs. "
            "`null` (default) defers to the admin env switch `EXTERNAL_URL_FETCH_ENABLED`. "
            "`false` opts this app out even when the admin allows it. "
            "`true` is a no-op when admin allows; the admin gate is a hard cap."
        ),
    )
    host_allowlist: list[str] | None = Field(
        default=None,
        description=(
            "Per-app override for the allowed hosts on external URL fetches. "
            "`null` (default) defers to the admin env var "
            "`EXTERNAL_URL_FETCH_HOST_ALLOWLIST`. A non-empty list narrows the admin "
            "list (intersection); a host must be in both to be allowed. An explicit "
            "empty list locks this app out of all hosts. Patterns: exact host "
            "(`example.com`) or `*.example.com` for any subdomain."
        ),
    )


class Features(BaseModel):
    timestamp: TimestampConfig | None = Field(
        default_factory=ToolCallTimestampConfig,
        description="Time awareness configuration.",
    )
    file_loading: FileLoadingConfig = Field(
        default_factory=FileLoadingConfig,
        description="File loader configuration (download size limits, etc.).",
    )
    external_url_fetch: ExternalUrlFetchConfig = Field(
        default_factory=ExternalUrlFetchConfig,
        description=(
            "Per-app override for fetching external (non-DIAL) URLs. "
            "Operates within the admin cap set by `EXTERNAL_URL_FETCH_ENABLED`."
        ),
    )
    stage_display: StageDisplayConfig = Field(
        default_factory=StageDisplayConfig,
        description="Controls which stage levels are rendered to the user.",
    )
    dial_files: DialFilesConfig | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description="Built-in DIAL files tools (list / read / search / write / edit / delete / copy / move).",
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
    skills: list[SkillConfig] | None = Field(
        default=None,
        description="Optional list of user-configured agent skills.",
    )
    hooks: list[HookConfig] | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description="Config-driven hooks fired at named orchestrator seams.",
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
