from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from quickapp.config.application import StageDisplayLevel


class StageDisplaySettings(BaseSettings):
    model_config = SettingsConfigDict()

    stage_display_level: StageDisplayLevel | None = Field(
        default=None,
        description="Override stage display level for all apps regardless of app config.",
        alias="DEFAULT_STAGE_DISPLAY_LEVEL",
    )
