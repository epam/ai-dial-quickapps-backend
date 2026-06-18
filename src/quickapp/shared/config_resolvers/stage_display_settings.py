from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quickapp.config.application import StageDisplayLevel


class StageDisplaySettings(BaseSettings):
    """Operator-level override for stage display level. When set, wins over per-app config."""

    model_config = SettingsConfigDict()

    stage_display_level: StageDisplayLevel | None = Field(
        default=None,
        description="Override stage display level for all apps regardless of app config.",
        alias="DEFAULT_STAGE_DISPLAY_LEVEL",
    )

    @field_validator("stage_display_level", mode="before")
    @classmethod
    def _normalize_level(cls, v: object) -> object:
        return v.lower() if isinstance(v, str) else v
