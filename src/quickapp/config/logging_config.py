import logging
import logging.config
import os
from typing import Any

import uvicorn.logging
from pydantic import BaseModel, Field

from quickapp.config.utils import bool_env_var


class SingleLineFormatter(uvicorn.logging.DefaultFormatter):
    def format(self, record):
        res = super().format(record).replace("\n", r"\n")
        return res


DEFAULT_LOG_FORMAT = (
    "%(message)s"
    if os.environ.get("LOG_MODE") == "dev"
    else "%(asctime)s [%(levelname)s] |%(process)d| %(pathname)s:%(lineno)d: %(message)s"
)
DEFAULT_LOG_LEVEL = "INFO"


class LoggingConfig(BaseModel):
    log_format: str = Field(default=os.getenv("LOG_FORMAT", DEFAULT_LOG_FORMAT))
    log_level: str = Field(default=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL))
    quickapp_log_level: str = Field(default=os.getenv("QUICKAPP_LOG_LEVEL", DEFAULT_LOG_LEVEL))
    # by default kaleido and choreographer log a lot of unnecessary information on INFO level
    plotly_image_conversion_log_level: str = Field(
        default=os.getenv("PLOTLY_IMAGE_CONVERSION_LOG_LEVEL", "WARN")
    )
    log_multiline_mode_enabled: bool = bool_env_var("LOG_MULTILINE_LOG_ENABLED", False)

    def __init__(self, /, **data: Any) -> None:
        super().__init__(**data)
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
