"""
Single place for reading environment variables. All env names and defaults live here.
Domain configs (LoggingConfig, AgentRuntimeSettings, etc.) are built from this module
and can be bound in the injector for DI.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)


def _get_bool_env(key: str, default: bool = False) -> bool:
    raw = os.getenv(key, str(default)).lower()
    if raw not in ("true", "false"):
        logger.warning("Env variable `%s` has invalid boolean value `%s`", key, raw)
    return raw == "true"


def _get_int_env(key: str, default: int) -> int:
    raw = os.getenv(key, str(default))
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "Env variable `%s` has invalid int value `%s`, using default %s", key, raw, default
        )
        return default


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _default_log_format() -> str:
    if os.getenv("LOG_MODE") == "dev":
        return "%(message)s"
    return "%(asctime)s [%(levelname)s] |%(process)d| %(pathname)s:%(lineno)d: %(message)s"


def load_logging_config():  # -> LoggingConfig (imported locally to avoid circular import)
    from quickapp.config.logging_config import LoggingConfig

    return LoggingConfig(
        log_format=_get_env("LOG_FORMAT") or _default_log_format(),
        log_level=_get_env("LOG_LEVEL") or "INFO",
        quickapp_log_level=_get_env("QUICKAPP_LOG_LEVEL") or "INFO",
        plotly_image_conversion_log_level=_get_env("PLOTLY_IMAGE_CONVERSION_LOG_LEVEL") or "WARN",
        log_multiline_mode_enabled=_get_bool_env("LOG_MULTILINE_LOG_ENABLED", False),
    )


# ---------------------------------------------------------------------------
# Agent / runtime
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentRuntimeSettings:
    show_usage_statistics: bool
    chat_message_log_length: Optional[int]
    default_agent_max_iterations: int


def load_agent_runtime_settings() -> AgentRuntimeSettings:
    raw = _get_env("CHAT_MESSAGE_LOG_LEN")
    try:
        chat_message_log_length: Optional[int] = int(raw) if raw is not None else None
    except ValueError:
        chat_message_log_length = None
    return AgentRuntimeSettings(
        show_usage_statistics=_get_bool_env("SHOW_USAGE_STATISTICS", False),
        chat_message_log_length=chat_message_log_length,
        default_agent_max_iterations=_get_int_env("DEFAULT_AGENT_MAX_ITERATIONS", 15),
    )


# ---------------------------------------------------------------------------
# Presentation (usage stats, execution time stage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PresentationSettings:
    show_usage_statistics: bool
    show_execution_time_stage: bool


def load_presentation_settings() -> PresentationSettings:
    return PresentationSettings(
        show_usage_statistics=_get_bool_env("SHOW_USAGE_STATISTICS", False),
        show_execution_time_stage=_get_bool_env("SHOW_EXECUTION_TIME_STAGE", False),
    )


# ---------------------------------------------------------------------------
# Content downloader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentDownloaderSettings:
    file_size_limit: int


def load_content_downloader_settings() -> ContentDownloaderSettings:
    return ContentDownloaderSettings(
        file_size_limit=_get_int_env(
            "CONTENT_DOWNLOADER_FILE_SIZE_LIMIT", 20 * 1024 * 1024
        ),  # 20 MiB
    )
