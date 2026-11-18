from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quickapp.config.application import InitializationIssueLevel


class InitializationIssuesSettings(BaseSettings):
    """Deployment-wide default for the Initialization issues stage threshold."""

    model_config = SettingsConfigDict()

    level: InitializationIssueLevel = Field(
        default=InitializationIssueLevel.WARNING,
        description="Lowest issue level shown in the Initialization issues stage.",
        alias="DEFAULT_INITIALIZATION_ISSUES_LEVEL",
    )

    @field_validator("level", mode="before")
    @classmethod
    def _normalize_level(cls, v: object) -> object:
        return v.lower() if isinstance(v, str) else v
