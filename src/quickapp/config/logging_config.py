import logging
import logging.config

# aidial_sdk applies its own dictConfig at import time (aidial_sdk/application.py),
# setting uvicorn to propagate=False and aidial_sdk to WARNING with a private
# handler. Importing it here guarantees that side effect lands before our
# dictConfig below, so LoggingConfig always has the last word regardless of the
# caller's import order.
import aidial_sdk  # noqa: F401
import uvicorn.logging

from quickapp.config.logging_settings import LoggingSettings

# Loggers whose levels LoggingConfig pins explicitly. They carry no handlers of
# their own and propagate to the root logger, which owns the single "console"
# handler — and, when OTEL_LOGS_EXPORTER is set, the OTLP export handler that
# aidial-sdk attaches to root. Exposed so tests can snapshot/restore identical
# state.
MANAGED_LOGGER_NAMES: tuple[str, ...] = (
    "quickapp",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "httpx",
    "httpcore",
    "openai",
    "aidial_sdk",
)


class SingleLineFormatter(uvicorn.logging.DefaultFormatter):
    def format(self, record):
        res = super().format(record).replace("\n", r"\n")
        return res


class LoggingConfig:
    def __init__(self, settings: LoggingSettings) -> None:
        self._settings = settings
        logging.config.dictConfig(self._get_logging_config())

    def _formatter_kwargs(self) -> dict:
        return {
            "fmt": self._settings.log_format,
            "datefmt": self._settings.log_date_format,
            "use_colors": True,
        }

    def _get_logging_config(self) -> dict:
        per_logger_config = {
            name: {
                "handlers": [],
                "level": (
                    self._settings.quickapp_log_level
                    if name == "quickapp"
                    else self._settings.log_level
                ),
                # Must stay explicit: dictConfig leaves `propagate` untouched
                # when the key is absent, and the uvicorn CLI's default config
                # (applied before ours in production) sets it to False —
                # which would cut these loggers off from root and OTLP export.
                "propagate": True,
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
            # dictConfig strips any existing root handlers, and aidial-sdk
            # appends its OTLP LoggingHandler to root during DIALApp
            # construction — LoggingConfig must therefore run before the app
            # is built.
            "root": {
                "handlers": ["console"],
                "level": self._settings.log_level,
            },
            "loggers": per_logger_config,
        }
