import logging

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_LOG_FORMAT = "%(levelprefix)s | %(asctime)s | %(process)d | %(name)s | %(otel_context)s%(message)s"  # noqa: E501
_DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class LoggingSettings(BaseSettings):
    """Settings for logging, loaded from environment variables via the aliases below."""

    model_config = SettingsConfigDict()

    log_format: str = Field(default=_DEFAULT_LOG_FORMAT, alias="LOG_FORMAT")
    log_date_format: str = Field(default=_DEFAULT_LOG_DATE_FORMAT, alias="LOG_DATE_FORMAT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    quickapp_log_level: str = Field(default="INFO", alias="QUICKAPP_LOG_LEVEL")
