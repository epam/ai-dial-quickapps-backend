"""Presentation/UI-related settings. Lives in common to avoid circular imports with agent/application."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PresentationSettings(BaseSettings):
    """Presentation/UI-related settings (usage stats, execution time stage)."""

    model_config = SettingsConfigDict(env_ignore_extra=True)

    show_usage_statistics: bool = Field(
        default=False,
        description="Include usage in stream options",
        alias="SHOW_USAGE_STATISTICS",
    )
    show_execution_time_stage: bool = Field(
        default=False,
        description="Show execution time stage in response",
        alias="SHOW_EXECUTION_TIME_STAGE",
    )
