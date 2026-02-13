import logging
import logging.config

import uvicorn.logging

from quickapp.config.logging_settings import LoggingSettings


class SingleLineFormatter(uvicorn.logging.DefaultFormatter):
    def format(self, record):
        res = super().format(record).replace("\n", r"\n")
        return res


class LoggingConfig:
    def __init__(self, settings: LoggingSettings) -> None:
        self._settings = settings
        self._configure_logging()
        self._override_aidial_sdk_logger()

    def _get_logging_config(self) -> dict:
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "()": "logging.Formatter",
                    "fmt": self._settings.log_format,
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
            "loggers": {
                "quickapp": {
                    "handlers": ["console"],
                    "level": self._settings.quickapp_log_level,
                    "propagate": False,
                },
                # override third-party libs log format
                "uvicorn": {
                    "handlers": ["console"],
                    "level": self._settings.log_level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": self._settings.log_level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console"],
                    "level": self._settings.log_level,
                    "propagate": False,
                },
                "httpcore": {
                    "handlers": ["console"],
                    "level": self._settings.log_level,
                    "propagate": False,
                },
                "openai": {
                    "handlers": ["console"],
                    "level": self._settings.log_level,
                    "propagate": False,
                },
                "kaleido": {
                    "handlers": ["console"],
                    "level": self._settings.plotly_image_conversion_log_level,
                    "propagate": False,
                },
                "choreographer": {
                    "handlers": ["console"],
                    "level": self._settings.plotly_image_conversion_log_level,
                    "propagate": False,
                },
            },
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

        # Override "aidial_sdk" logger to meet same logging format
        from aidial_sdk import logger as aidial_sdk_logger

        aidial_sdk_logger.propagate = False
        aidial_sdk_logger.setLevel(self._settings.log_level)

        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(self._settings.log_format))

        aidial_sdk_logger.handlers = [handler]

    def _override_aidial_sdk_logger(self) -> None:
        from aidial_sdk import logger as aidial_sdk_logger  # type: ignore

        aidial_sdk_logger.propagate = False
        aidial_sdk_logger.setLevel("INFO")

        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(self._settings.log_format))

        aidial_sdk_logger.handlers = [handler]
