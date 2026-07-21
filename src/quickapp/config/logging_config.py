import logging

# Importing from aidial_sdk triggers configure_sdk_logger() (application.py),
# which gives aidial_sdk and uvicorn private handlers and sets uvicorn to
# propagate=False. LoggingConfig undoes both below, so it always has the last
# word regardless of the caller's import order.
from aidial_sdk import LogConfig, configure_root_logger

from quickapp.common.payload_logging import configure_payload_logging
from quickapp.config._otel_aware_formatter import OtelAwareFormatter
from quickapp.config.logging_settings import LoggingSettings

logger = logging.getLogger(__name__)

# Loggers whose levels LoggingConfig pins explicitly. They carry no handlers of
# their own and propagate to the root logger, which owns the single console
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


class _ExcTextBlankingFormatter(logging.Formatter):
    """Blank exc_text on records without an exception before JSON rendering.

    LogRecord initializes exc_text to None and the SDK JSON formatter
    interpolates %(exc_text)s with str() semantics, so plain records would
    render '"exception": "None"'. Exception records are unaffected: the inner
    formatter fills exc_text from exc_info whenever it is falsy.
    """

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self._inner = inner

    def format(self, record: logging.LogRecord) -> str:
        if record.exc_text is None:
            record.exc_text = ""
        return self._inner.format(record)


class LoggingConfig:
    """Route all logging through one console handler on the root logger.

    The handler and format selection belong to aidial-sdk's
    configure_root_logger(): DIAL_SDK_LOG_FORMAT=json selects the SDK's
    escape-safe JSON formatter (template via DIAL_SDK_JSON_LOG_FORMAT, otel*
    trace fields auto-added), text selects a %-style format via
    DIAL_SDK_TEXT_LOG_FORMAT. When no text format is requested through the
    SDK vars, the SDK formatter is replaced with OtelAwareFormatter and this
    service's default format — the SDK text formatter cannot render the
    conditional %(otel_context)s trace block. The deprecated LOG_FORMAT /
    LOG_DATE_FORMAT vars still feed that formatter when set, and win, so
    existing deployments keep their output while the startup warning nudges
    them to migrate.

    Level pinning stays local: configure_root_logger() deliberately leaves
    per-logger levels to the application.
    """

    def __init__(self, settings: LoggingSettings) -> None:
        self._settings = settings
        # configure_root_logger drops competing stderr console handlers and
        # installs its own, but leaves non-console handlers alone — the OTLP
        # LoggingHandler that aidial-sdk attaches to root during DIALApp
        # construction survives whether it is added before or after this call.
        # Caveat: with the deprecated OTEL_PYTHON_LOG_CORRELATION=true set, the
        # SDK defers the console to OTEL's own handler and none of the
        # formatting below applies — drop that variable from deployments.
        configure_root_logger(self._build_log_config())
        self._pin_logger_levels()
        configure_payload_logging(settings.log_payloads, settings.log_payloads_max_length)
        self._warn_deprecated_vars()

    def _build_log_config(self) -> LogConfig:
        settings = self._settings
        # The format values are passed through from settings so the SDK's own
        # env fallbacks never fire — LoggingSettings is the single reader.
        # (LogConfig.level still resolves from DIAL_SDK_LOG, but the result is
        # overridden by _pin_logger_levels.)
        config = LogConfig(
            log_format=settings.log_output_format,
            text_format=settings.text_log_format,
            json_format=settings.json_log_format,
        )
        if settings.log_output_format == "json":
            config.formatter = _ExcTextBlankingFormatter(config.formatter)
        elif settings.text_log_format is None or settings.deprecated_format_vars_set:
            config.formatter = OtelAwareFormatter(
                fmt=settings.log_format,
                datefmt=settings.log_date_format,
                use_colors=True,
            )
        return config

    def _level_for(self, name: str) -> str:
        if name == "quickapp":
            return self._settings.quickapp_log_level
        if name in PAYLOAD_CAPPED_LOGGERS and not self._settings.log_payloads:
            return _cap_at_info(self._settings.log_level)
        return self._settings.log_level

    def _pin_logger_levels(self) -> None:
        logging.getLogger().setLevel(self._settings.log_level)
        for name in MANAGED_LOGGER_NAMES:
            managed = logging.getLogger(name)
            # configure_root_logger already resets its own four names
            # (aidial_sdk, uvicorn*); the explicit reset here covers the rest
            # against the uvicorn CLI's default config (applied before ours in
            # production), which attaches handlers and sets propagate=False —
            # cutting loggers off from root, its console handler, and OTLP
            # export. Kept uniform across all managed names for simplicity.
            managed.handlers = []
            managed.propagate = True
            managed.setLevel(self._level_for(name))

    def _warn_deprecated_vars(self) -> None:
        deprecated = self._settings.deprecated_format_vars_set
        if deprecated:
            logger.warning(
                "%s deprecated and will be removed in a future release; "
                "use DIAL_SDK_TEXT_LOG_FORMAT or DIAL_SDK_LOG_FORMAT=json "
                "instead (see docs/logging.md).",
                " and ".join(deprecated),
            )
