import logging
from typing import Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_LOG_FORMAT = (
    "%(asctime)s [%(levelname)s] |%(process)d| %(pathname)s:%(lineno)d: %(message)s"
)


class LoggingSettings(BaseSettings):
    """Settings for logging. Use from_env() to load from os.environ (avoids pydantic-settings env quirks)."""

    model_config = SettingsConfigDict(env_ignore_extra=True)

    log_mode: Optional[str] = Field(default=None, alias="LOG_MODE")
    log_format: str = Field(default=_DEFAULT_LOG_FORMAT, alias="LOG_FORMAT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    quickapp_log_level: str = Field(default="INFO", alias="QUICKAPP_LOG_LEVEL")
    plotly_image_conversion_log_level: str = Field(
        default="WARN",
        alias="PLOTLY_IMAGE_CONVERSION_LOG_LEVEL",
    )
    log_multiline_mode_enabled: bool = Field(
        default=False,
        alias="LOG_MULTILINE_LOG_ENABLED",
    )

    @computed_field
    @property
    def resolved_log_format(self) -> str:
        if self.log_mode == "dev":
            return "%(filename)s:%(lineno)d - %(message)s"
        return self.log_format
