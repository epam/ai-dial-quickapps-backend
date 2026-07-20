from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_LOG_FORMAT = "%(levelprefix)s | %(asctime)s | %(process)d | %(name)s | %(otel_context)s%(message)s"  # noqa: E501
_DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# The aidial-sdk 0.38 default template plus an "exception" leaf: the SDK
# renders only the fields the template references, so without it
# logger.exception() tracebacks would be silently dropped from JSON output.
# Pinned deliberately (not derived from the SDK constant): this is the
# service's documented output contract and must not drift with SDK defaults.
_DEFAULT_JSON_LOG_FORMAT: dict[str, Any] = {
    "level": "%(levelname)s",
    "time": "%(asctime)s",
    "logger": "%(name)s",
    "process": "%(process)d",
    "message": "%(message)s",
    "exception": "%(exc_text)s",
}

# Fields whose env vars are deprecated. Still honored (and they win over the
# DIAL_SDK_* successors) so existing deployments keep their output, but
# LoggingConfig warns at startup; support will be removed in a future release.
_DEPRECATED_FIELDS: tuple[str, ...] = ("log_format", "log_date_format")


class LoggingSettings(BaseSettings):
    """Settings for logging, loaded from environment variables via the aliases below."""

    model_config = SettingsConfigDict()

    # Deprecated: use DIAL_SDK_TEXT_LOG_FORMAT / DIAL_SDK_LOG_FORMAT=json.
    log_format: str = Field(default=_DEFAULT_LOG_FORMAT, alias="LOG_FORMAT")
    # Deprecated: the date format is fixed to the default going forward.
    log_date_format: str = Field(default=_DEFAULT_LOG_DATE_FORMAT, alias="LOG_DATE_FORMAT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    quickapp_log_level: str = Field(default="INFO", alias="QUICKAPP_LOG_LEVEL")
    # The DIAL_SDK_* vars are shared with aidial-sdk: the SDK reads them for
    # its own loggers at import time, LoggingConfig reads them here to shape
    # the root console handler — one switch flips both.
    log_output_format: Literal["text", "json"] = Field(default="text", alias="DIAL_SDK_LOG_FORMAT")
    text_log_format: str | None = Field(default=None, alias="DIAL_SDK_TEXT_LOG_FORMAT")
    json_log_format: dict[str, Any] = Field(
        default=_DEFAULT_JSON_LOG_FORMAT, alias="DIAL_SDK_JSON_LOG_FORMAT"
    )
    # Payload-debugging switch (content policy, design #434 / issue #436). When false
    # (default), content-bearing records are not emitted at any level, and the
    # payload-capable third-party loggers (openai/httpx/httpcore) are capped at INFO. When
    # true, those records are emitted at DEBUG with each field truncated. Local development
    # only — must not be enabled in shared environments.
    log_payloads: bool = Field(default=False, alias="LOG_PAYLOADS")
    log_payloads_max_length: int = Field(default=2000, alias="LOG_PAYLOADS_MAX_LENGTH")

    @field_validator("log_output_format", mode="before")
    @classmethod
    def _lowercase_output_format(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @property
    def deprecated_format_vars_set(self) -> tuple[str, ...]:
        """Names of deprecated logging env vars present in the environment."""
        return tuple(
            alias
            for field in _DEPRECATED_FIELDS
            if (alias := type(self).model_fields[field].alias) is not None
            and field in self.model_fields_set
        )
