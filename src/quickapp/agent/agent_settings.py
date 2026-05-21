"""Agent module settings. Env vars use aliases to match existing names."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Settings for the agent module. Loaded from env with aliases below."""

    model_config = SettingsConfigDict()

    chat_message_log_length: int | None = Field(
        default=None,
        description="Max length for chat message log preview (-1 or unset = no truncation)",
        alias="CHAT_MESSAGE_LOG_LEN",
    )
    default_agent_max_iterations: int = Field(
        default=15,
        description="Max orchestrator(agent) operations",
        alias="DEFAULT_AGENT_MAX_ITERATIONS",
    )
    default_orchestrator_deployment_id: str | None = Field(
        default=None,
        description=(
            "Default DIAL deployment id used as the orchestrator model when a "
            "QuickApp manifest omits orchestrator.deployment."
        ),
        alias="DEFAULT_ORCHESTRATOR_DEPLOYMENT_ID",
    )

    @field_validator("default_orchestrator_deployment_id", mode="after")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        # BaseSettings returns "" (not None) for an empty/whitespace env value.
        # Normalize so downstream code only sees a real id or None.
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
