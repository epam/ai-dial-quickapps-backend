import logging

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_LOG_FORMAT = (
    "%(asctime)s [%(levelname)s] |%(process)d| %(pathname)s:%(lineno)d: %(message)s"
)


class LoggingSettings(BaseSettings):
    """Settings for logging. Use from_env() to load from os.environ (avoids pydantic-settings env quirks)."""

    model_config = SettingsConfigDict()

    log_format: str = Field(default=_DEFAULT_LOG_FORMAT, alias="LOG_FORMAT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    quickapp_log_level: str = Field(default="INFO", alias="QUICKAPP_LOG_LEVEL")
    log_multiline_mode_enabled: bool = Field(
        default=False,
        alias="LOG_MULTILINE_LOG_ENABLED",
    )
