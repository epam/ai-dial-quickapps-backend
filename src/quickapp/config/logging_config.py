import logging
import logging.config

# aidial_sdk applies its own dictConfig at import time (aidial_sdk/application.py),
# setting uvicorn to propagate=False and aidial_sdk to WARNING with a private
# handler. Importing it here guarantees that side effect lands before our
# dictConfig below, so LoggingConfig always has the last word regardless of the
# caller's import order.
import aidial_sdk  # noqa: F401

from quickapp.common.payload_logging import configure_payload_logging
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

# Third-party loggers that emit payload content at DEBUG (openai logs full
# chat-completion request bodies; httpx/httpcore log wire-level detail). They are capped
# at INFO unless the payload switch is on, so raising LOG_LEVEL alone never brings their
# payloads into the pipeline (design #434 / issue #436).
PAYLOAD_CAPPED_LOGGERS: tuple[str, ...] = ("openai", "httpx", "httpcore")


def _cap_at_info(level_name: str) -> str:
    """Return ``level_name`` unless it is more verbose than INFO, in which case ``INFO``.

    Only ever raises the floor to INFO — an already-restrictive level (WARNING/ERROR) is
    left untouched.
    """
    numeric = logging.getLevelNamesMapping().get(level_name.upper(), logging.INFO)
    return "INFO" if numeric < logging.INFO else level_name


class LoggingConfig:
    def __init__(self, settings: LoggingSettings) -> None:
        self._settings = settings
        logging.config.dictConfig(self._get_logging_config())
        configure_payload_logging(settings.log_payloads, settings.log_payloads_max_length)

    def _formatter_kwargs(self) -> dict:
        return {
            "fmt": self._settings.log_format,
            "datefmt": self._settings.log_date_format,
            "use_colors": True,
        }

    def _level_for(self, name: str) -> str:
        if name == "quickapp":
            return self._settings.quickapp_log_level
        if name in PAYLOAD_CAPPED_LOGGERS and not self._settings.log_payloads:
            return _cap_at_info(self._settings.log_level)
        return self._settings.log_level

    def _get_logging_config(self) -> dict:
        per_logger_config = {
            name: {
                "handlers": [],
                "level": self._level_for(name),
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
