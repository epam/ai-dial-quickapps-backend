import logging
import logging.config

import uvicorn.logging

from quickapp.config._otel_log_filter import OtelDefaultsFilter
from quickapp.config.logging_settings import LoggingSettings

# Loggers that LoggingConfig pins to the shared "console" handler with
# propagate=False. Exposed so tests can snapshot/restore identical state.
MANAGED_LOGGER_NAMES: tuple[str, ...] = (
    "quickapp",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "httpcore",
    "openai",
)


class SingleLineFormatter(uvicorn.logging.DefaultFormatter):
    def format(self, record):
        res = super().format(record).replace("\n", r"\n")
        return res


class LoggingConfig:
    def __init__(self, settings: LoggingSettings) -> None:
        self._settings = settings
        self._configure_logging()
        self._override_aidial_sdk_logger()

    def _formatter_kwargs(self) -> dict:
        return {
            "fmt": self._settings.log_format,
            "datefmt": self._settings.log_date_format,
            # None lets uvicorn autodetect TTY — avoids ANSI bytes when stdout
            # is piped to a log shipper.
            "use_colors": None,
        }

    def _get_logging_config(self) -> dict:
        per_logger_config = {
            name: {
                "handlers": ["console"],
                "level": (
                    self._settings.quickapp_log_level
                    if name == "quickapp"
                    else self._settings.log_level
                ),
                "propagate": False,
            }
            for name in MANAGED_LOGGER_NAMES
        }
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "otel_defaults": {
                    "()": "quickapp.config._otel_log_filter.OtelDefaultsFilter",
                },
            },
            "formatters": {
                "default": {
                    "()": "uvicorn.logging.DefaultFormatter",
                    **self._formatter_kwargs(),
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["otel_defaults"],
                },
            },
            "root": {
                "handlers": ["console"],
                "level": self._settings.log_level,
            },
            "loggers": per_logger_config,
        }

    def _configure_logging(self) -> None:
        logging.config.dictConfig(self._get_logging_config())

        # Ensure quickapp logger level is applied (e.g. QUICKAPP_LOG_LEVEL=DEBUG)
        quickapp_logger = logging.getLogger("quickapp")
        level = getattr(
            logging,
            self._settings.quickapp_log_level.upper(),
            logging.INFO,
        )
        quickapp_logger.setLevel(level)

    def _override_aidial_sdk_logger(self) -> None:
        from aidial_sdk import logger as aidial_sdk_logger  # type: ignore

        aidial_sdk_logger.propagate = False
        aidial_sdk_logger.setLevel(self._settings.log_level)

        handler = logging.StreamHandler()
        handler.setFormatter(uvicorn.logging.DefaultFormatter(**self._formatter_kwargs()))
        handler.addFilter(OtelDefaultsFilter())

        aidial_sdk_logger.handlers = [handler]
