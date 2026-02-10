import logging
import logging.config

import uvicorn.logging
from pydantic import BaseModel, Field

from quickapp.config.logging_settings import LoggingSettings


class SingleLineFormatter(uvicorn.logging.DefaultFormatter):
    def format(self, record):
        res = super().format(record).replace("\n", r"\n")
        return res


DEFAULT_LOG_FORMAT = (
    "%(asctime)s [%(levelname)s] |%(process)d| %(pathname)s:%(lineno)d: %(message)s"
)
DEFAULT_LOG_LEVEL = "INFO"


class LoggingConfig(BaseModel):
    log_format: str = Field(default=DEFAULT_LOG_FORMAT)
    log_level: str = Field(default=DEFAULT_LOG_LEVEL)
    quickapp_log_level: str = Field(default=DEFAULT_LOG_LEVEL)
    plotly_image_conversion_log_level: str = Field(default="WARN")
    log_multiline_mode_enabled: bool = Field(default=False)

    def __init__(self, settings: LoggingSettings) -> None:
        super().__init__(**settings.model_dump())
        self.configure_logging()
        self.override_aidial_sdk_logger(self.log_format)

    def get_logging_config(self):
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "()": "logging.Formatter",
                    "fmt": self.log_format,
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
                "level": self.log_level,
            },
            "loggers": {
                "quickapp": {
                    "handlers": ["console"],
                    "level": self.quickapp_log_level,
                    "propagate": False,
                },
                # override third-party libs log format
                "uvicorn": {"handlers": ["console"], "level": self.log_level, "propagate": False},
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": self.log_level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console"],
                    "level": self.log_level,
                    "propagate": False,
                },
                "httpcore": {
                    "handlers": ["console"],
                    "level": self.log_level,
                    "propagate": False,
                },
                "openai": {"handlers": ["console"], "level": self.log_level, "propagate": False},
                "kaleido": {
                    "handlers": ["console"],
                    "level": self.plotly_image_conversion_log_level,
                    "propagate": False,
                },
                "choreographer": {
                    "handlers": ["console"],
                    "level": self.plotly_image_conversion_log_level,
                    "propagate": False,
                },
            },
        }

    def configure_logging(self):
        logging.config.dictConfig(self.get_logging_config())

        # Ensure quickapp logger level is applied (e.g. QUICKAPP_LOG_LEVEL=DEBUG)
        quickapp_logger = logging.getLogger("quickapp")
        level = getattr(
            logging,
            self.quickapp_log_level.upper(),
            logging.INFO,
        )
        quickapp_logger.setLevel(level)

        # Override "aidial_sdk" logger to meet same logging format
        from aidial_sdk import logger as aidial_sdk_logger

        aidial_sdk_logger.propagate = False
        aidial_sdk_logger.setLevel(self.log_level)

        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(self.log_format))

        aidial_sdk_logger.handlers = [handler]

    @staticmethod
    def override_aidial_sdk_logger(log_format: str):
        from aidial_sdk import logger as aidial_sdk_logger  # type: ignore

        aidial_sdk_logger.propagate = False
        aidial_sdk_logger.setLevel("INFO")  # DIALConfig.LOG_LEVEL)

        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(log_format))

        aidial_sdk_logger.handlers = [handler]
