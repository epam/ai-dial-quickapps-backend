import logging
import logging.config

from quickapp.config._otel_aware_formatter import OtelAwareFormatter
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


class LoggingConfig:
    def __init__(self, settings: LoggingSettings) -> None:
        self._settings = settings
        self._configure_logging()
        self._override_aidial_sdk_logger()

    def _formatter_kwargs(self) -> dict:
        return {
            "fmt": self._settings.log_format,
            "datefmt": self._settings.log_date_format,
            "use_colors": True,
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
            "formatters": {
                "default": {
                    "()": "quickapp.config._otel_aware_formatter.OtelAwareFormatter",
                    **self._formatter_kwargs(),
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
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
        handler.setFormatter(OtelAwareFormatter(**self._formatter_kwargs()))

        aidial_sdk_logger.handlers = [handler]
