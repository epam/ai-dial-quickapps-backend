import io
import logging
import re

import pytest
import uvicorn.logging

from quickapp.config._otel_aware_formatter import OtelAwareFormatter
from quickapp.config.logging_config import MANAGED_LOGGER_NAMES, LoggingConfig
from quickapp.config.logging_settings import LoggingSettings


def _make_record(name: str = "quickapp.test", message: str = "hi") -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=None,
        exc_info=None,
    )


def _build_formatter() -> OtelAwareFormatter:
    settings = LoggingSettings()
    return OtelAwareFormatter(
        fmt=settings.log_format,
        datefmt=settings.log_date_format,
        use_colors=False,
    )


_TOUCHED_LOGGERS = ("", *MANAGED_LOGGER_NAMES, "aidial_sdk")


@pytest.fixture
def reset_logging_state():
    """Snapshot/restore every logger LoggingConfig touches.

    Logging state is global — without this fixture, calling LoggingConfig in
    a test leaks `propagate=False`, custom handlers, and modified levels into
    every later test that depends on caplog or default propagation.
    """
    snapshots = []
    for name in _TOUCHED_LOGGERS:
        logger = logging.getLogger(name)
        snapshots.append(
            (
                logger,
                list(logger.handlers),
                logger.level,
                logger.propagate,
                list(logger.filters),
            )
        )
    saved_factory = logging.getLogRecordFactory()

    yield

    logging.setLogRecordFactory(saved_factory)
    for logger, handlers, level, propagate, filters in snapshots:
        logger.handlers = handlers
        logger.setLevel(level)
        logger.propagate = propagate
        logger.filters = filters


class TestOtelAwareFormatter:
    def test_omits_block_when_attribute_missing(self):
        formatter = _build_formatter()
        output = formatter.format(_make_record(message="plain"))

        assert "trace_id=" not in output
        assert "span_id=" not in output
        assert output.endswith("plain")

    def test_omits_block_when_trace_id_is_zero(self):
        record = _make_record(message="zero-trace")
        record.otelTraceID = "0"
        record.otelSpanID = "0"
        record.otelServiceName = ""
        record.otelTraceSampled = False

        output = _build_formatter().format(record)

        assert "trace_id=" not in output
        assert "span_id=" not in output
        assert output.endswith("zero-trace")

    def test_renders_block_when_trace_active(self):
        record = _make_record(message="with-trace")
        record.otelTraceID = "3fdd3958e0a9ed92c563f5af15009c15"
        record.otelSpanID = "4cc359214676ab9a"
        record.otelServiceName = "quickapps2"
        record.otelTraceSampled = True

        output = _build_formatter().format(record)

        assert (
            "[trace_id=3fdd3958e0a9ed92c563f5af15009c15 "
            "span_id=4cc359214676ab9a "
            "resource.service.name=quickapps2 "
            "trace_sampled=True] | with-trace"
        ) in output


class TestLoggingConfigFormat:
    def test_default_format_renders_without_otel_runtime(self, capsys, reset_logging_state):
        LoggingConfig(LoggingSettings())

        logging.getLogger("quickapp.x").info("hello-world")

        captured = capsys.readouterr().err
        assert "trace_id=" not in captured
        assert "span_id=" not in captured
        assert " | " in captured
        assert captured.rstrip().endswith("hello-world")

    def test_default_format_renders_with_simulated_otel_record(self, capsys, reset_logging_state):
        LoggingConfig(LoggingSettings())

        original_factory = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            record = original_factory(*args, **kwargs)
            record.otelTraceID = "3fdd3958e0a9ed92c563f5af15009c15"
            record.otelSpanID = "4cc359214676ab9a"
            record.otelServiceName = "quickapps2"
            record.otelTraceSampled = True
            return record

        logging.setLogRecordFactory(factory)
        try:
            logging.getLogger("quickapp.x").info("with-trace")
        finally:
            logging.setLogRecordFactory(original_factory)

        captured = capsys.readouterr().err
        assert "trace_id=3fdd3958e0a9ed92c563f5af15009c15" in captured
        assert "span_id=4cc359214676ab9a" in captured
        assert "resource.service.name=quickapps2" in captured
        assert "trace_sampled=True" in captured
        assert "with-trace" in captured

    def test_levelprefix_is_rendered(self, reset_logging_state):
        LoggingConfig(LoggingSettings())

        # The shared "console" handler is on the root logger plus child loggers.
        handler = logging.getLogger("quickapp").handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert isinstance(handler.formatter, OtelAwareFormatter)
        assert isinstance(handler.formatter, uvicorn.logging.DefaultFormatter)

        buf = io.StringIO()
        handler.stream = buf
        logging.getLogger("quickapp.x").info("level-test")
        output = buf.getvalue()

        # `%(levelprefix)s` produces "INFO:    " (with optional ANSI colour wrap).
        # Strip ANSI escape sequences before asserting.
        plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
        assert plain.lstrip().startswith("INFO:")

    def test_log_date_format_override(self, monkeypatch, reset_logging_state):
        monkeypatch.setenv("LOG_DATE_FORMAT", "%H:%M")

        settings = LoggingSettings()
        assert settings.log_date_format == "%H:%M"

        LoggingConfig(settings)

        handler = logging.getLogger("quickapp").handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        buf = io.StringIO()
        handler.stream = buf
        logging.getLogger("quickapp.x").info("date-test")

        plain = re.sub(r"\x1b\[[0-9;]*m", "", buf.getvalue())
        # The pipe-separated layout puts the timestamp in the second field.
        fields = [f.strip() for f in plain.split("|")]
        assert re.fullmatch(r"\d{2}:\d{2}", fields[1])
