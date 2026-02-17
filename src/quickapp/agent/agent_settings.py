"""Agent module settings. Env vars use aliases to match existing names."""

from pydantic import Field
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
