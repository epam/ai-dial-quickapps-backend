import io
import json
import logging
import re

import pytest
import uvicorn.logging
from pydantic import ValidationError

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


def _root_console_handler() -> logging.StreamHandler:
    # configure_root_logger appends its console handler last; handlers pytest
    # installs on root (non-stderr capture streams) survive in front of it.
    handler = logging.getLogger().handlers[-1]
    assert isinstance(handler, logging.StreamHandler)
    return handler


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _emit_and_capture(message: str) -> str:
    """Log through the console handler into a buffer; return it ANSI-stripped."""
    handler = _root_console_handler()
    buf = io.StringIO()
    handler.stream = buf
    logging.getLogger("quickapp.x").info(message)
    return _ANSI_ESCAPE.sub("", buf.getvalue())


def _stamp_otel_fields_on_records(**fields: object) -> None:
    """Install a record factory stamping otel* fields on every record.

    No manual restore needed — reset_logging_state restores the factory.
    """
    original_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = original_factory(*args, **kwargs)
        for key, value in fields.items():
            setattr(record, key, value)
        return record

    logging.setLogRecordFactory(factory)


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


_TOUCHED_LOGGERS = ("", *MANAGED_LOGGER_NAMES)


@pytest.fixture
def no_format_env(monkeypatch):
    """Clear the whole LoggingSettings env surface so tests exercise defaults."""
    for field_info in LoggingSettings.model_fields.values():
        if field_info.alias:
            monkeypatch.delenv(field_info.alias, raising=False)


@pytest.fixture
def reset_logging_state():
    """Snapshot/restore every logger LoggingConfig touches.

    Logging state is global — without this fixture, calling LoggingConfig in
    a test leaks modified `propagate` flags, handlers, and levels into every
    later test that depends on caplog or default propagation.
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


@pytest.fixture
def json_env(monkeypatch, no_format_env, reset_logging_state):
    """Clean env with DIAL_SDK_LOG_FORMAT=json. Tests construct LoggingConfig
    themselves: the console handler binds sys.stderr by value, so it must run
    while the test's capsys capture is active, not during fixture setup."""
    monkeypatch.setenv("DIAL_SDK_LOG_FORMAT", "json")


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

        _stamp_otel_fields_on_records(
            otelTraceID="3fdd3958e0a9ed92c563f5af15009c15",
            otelSpanID="4cc359214676ab9a",
            otelServiceName="quickapps2",
            otelTraceSampled=True,
        )
        logging.getLogger("quickapp.x").info("with-trace")

        captured = capsys.readouterr().err
        assert "trace_id=3fdd3958e0a9ed92c563f5af15009c15" in captured
        assert "span_id=4cc359214676ab9a" in captured
        assert "resource.service.name=quickapps2" in captured
        assert "trace_sampled=True" in captured
        assert "with-trace" in captured

    def test_levelprefix_is_rendered(self, reset_logging_state):
        LoggingConfig(LoggingSettings())

        # The shared console handler lives on the root logger only; managed
        # loggers propagate to it.
        handler = _root_console_handler()
        assert isinstance(handler.formatter, OtelAwareFormatter)
        assert isinstance(handler.formatter, uvicorn.logging.DefaultFormatter)

        # `%(levelprefix)s` produces "INFO:    " (with optional ANSI colour wrap).
        plain = _emit_and_capture("level-test")
        assert plain.lstrip().startswith("INFO:")

    def test_log_date_format_override(self, monkeypatch, reset_logging_state):
        monkeypatch.setenv("LOG_DATE_FORMAT", "%H:%M")

        settings = LoggingSettings()
        assert settings.log_date_format == "%H:%M"

        LoggingConfig(settings)

        plain = _emit_and_capture("date-test")
        # The pipe-separated layout puts the timestamp in the second field.
        fields = [f.strip() for f in plain.split("|")]
        assert re.fullmatch(r"\d{2}:\d{2}", fields[1])


class TestRecordRouting:
    """Managed loggers must propagate to root, where the console handler and
    the OTLP handler aidial-sdk attaches (issue #433) both live."""

    def test_managed_loggers_route_to_root_handler_exactly_once(self, reset_logging_state):
        LoggingConfig(LoggingSettings())

        # Mirrors how aidial-sdk attaches its OTLP LoggingHandler to root
        # after LoggingConfig has run.
        recorder = _RecordingHandler()
        logging.getLogger().addHandler(recorder)

        emitting_loggers = ("quickapp.x", *(n for n in MANAGED_LOGGER_NAMES if n != "quickapp"))
        for name in emitting_loggers:
            logging.getLogger(name).info("routing-check")

        arrived = [record.name for record in recorder.records]
        assert sorted(arrived) == sorted(emitting_loggers)

    def test_console_output_has_no_duplicates(self, capsys, reset_logging_state):
        LoggingConfig(LoggingSettings())

        logging.getLogger("quickapp.x").info("only-once")

        assert capsys.readouterr().err.count("only-once") == 1

    def test_preexisting_uvicorn_state_is_reset(self, reset_logging_state):
        # Simulate the uvicorn CLI's default log config, which runs before
        # LoggingConfig in production and severs uvicorn.* from root.
        uvicorn_logger = logging.getLogger("uvicorn")
        uvicorn_logger.addHandler(logging.NullHandler())
        uvicorn_logger.propagate = False

        LoggingConfig(LoggingSettings())

        assert uvicorn_logger.handlers == []
        assert uvicorn_logger.propagate is True

    def test_aidial_sdk_import_time_config_is_overridden(self, reset_logging_state):
        # aidial_sdk runs configure_sdk_logger() at import time (application.py):
        # aidial_sdk and uvicorn get private handlers, uvicorn propagate=False
        # and aidial_sdk a WARNING level. LoggingConfig must undo all of it.
        from aidial_sdk.utils.log_config import configure_sdk_logger

        configure_sdk_logger()

        LoggingConfig(LoggingSettings())

        for name in ("uvicorn", "aidial_sdk"):
            managed = logging.getLogger(name)
            assert managed.handlers == []
            assert managed.propagate is True
        assert logging.getLogger("aidial_sdk").level == logging.INFO

    def test_quickapp_level_pin_filters_debug(self, monkeypatch, reset_logging_state):
        monkeypatch.delenv("QUICKAPP_LOG_LEVEL", raising=False)
        LoggingConfig(LoggingSettings())

        recorder = _RecordingHandler()
        logging.getLogger().addHandler(recorder)

        # The level pin filters at the emitting logger, even though the root
        # handlers themselves accept everything.
        logging.getLogger("quickapp.x").debug("filtered-out")

        assert recorder.records == []


class TestJsonOutputMode:
    def test_emits_escape_safe_single_line(self, json_env, capsys):
        LoggingConfig(LoggingSettings())

        logging.getLogger("quickapp.x").info('has "quotes" and\na newline')

        err = capsys.readouterr().err
        assert err.count("\n") == 1
        payload = json.loads(err)
        assert payload["message"] == 'has "quotes" and\na newline'
        assert payload["logger"] == "quickapp.x"
        assert payload["level"] == "INFO"

    def test_exception_records_carry_traceback(self, json_env, capsys):
        LoggingConfig(LoggingSettings())

        try:
            raise ValueError("kaboom")
        except ValueError:
            logging.getLogger("quickapp.x").exception("op failed")

        payload = json.loads(capsys.readouterr().err)
        assert payload["message"] == "op failed"
        assert "Traceback" in payload["exception"]
        assert "ValueError: kaboom" in payload["exception"]

    def test_plain_records_render_empty_exception(self, json_env, capsys):
        LoggingConfig(LoggingSettings())

        logging.getLogger("quickapp.x").info("no-error")

        payload = json.loads(capsys.readouterr().err)
        # Not the literal "None" that %(exc_text)s would render by default.
        assert payload["exception"] == ""

    def test_otel_fields_are_auto_added(self, json_env, capsys):
        LoggingConfig(LoggingSettings())

        _stamp_otel_fields_on_records(otelTraceID="3fdd3958e0a9ed92c563f5af15009c15")
        logging.getLogger("quickapp.x").info("with-trace")

        payload = json.loads(capsys.readouterr().err)
        assert payload["otelTraceID"] == "3fdd3958e0a9ed92c563f5af15009c15"

    def test_template_override_via_env(self, json_env, monkeypatch, capsys):
        monkeypatch.setenv(
            "DIAL_SDK_JSON_LOG_FORMAT", '{"lvl": "%(levelname)s", "msg": "%(message)s"}'
        )
        LoggingConfig(LoggingSettings())

        logging.getLogger("quickapp.x").info("templated")

        payload = json.loads(capsys.readouterr().err)
        assert payload == {"lvl": "INFO", "msg": "templated"}


class TestTextFormatSelection:
    def test_sdk_text_format_is_honored(self, monkeypatch, no_format_env, reset_logging_state):
        monkeypatch.setenv("DIAL_SDK_TEXT_LOG_FORMAT", "%(levelname)s :: %(message)s")
        LoggingConfig(LoggingSettings())

        # The SDK-built formatter, not the OtelAwareFormatter override.
        handler = _root_console_handler()
        assert isinstance(handler.formatter, uvicorn.logging.DefaultFormatter)
        assert not isinstance(handler.formatter, OtelAwareFormatter)

        assert _emit_and_capture("sdk-text").strip() == "INFO :: sdk-text"

    def test_deprecated_log_format_wins_over_sdk_text_format(
        self, monkeypatch, no_format_env, reset_logging_state
    ):
        monkeypatch.setenv("LOG_FORMAT", "%(message)s !!")
        monkeypatch.setenv("DIAL_SDK_TEXT_LOG_FORMAT", "%(levelname)s :: %(message)s")
        LoggingConfig(LoggingSettings())

        assert isinstance(_root_console_handler().formatter, OtelAwareFormatter)
        assert _emit_and_capture("legacy-wins").strip() == "legacy-wins !!"

    def test_deprecated_vars_warn_at_startup(
        self, monkeypatch, capsys, no_format_env, reset_logging_state
    ):
        monkeypatch.setenv("LOG_DATE_FORMAT", "%H:%M")

        LoggingConfig(LoggingSettings())

        err = capsys.readouterr().err
        assert "LOG_DATE_FORMAT deprecated" in err
        assert "DIAL_SDK_TEXT_LOG_FORMAT" in err

    def test_no_deprecation_warning_by_default(self, capsys, no_format_env, reset_logging_state):
        LoggingConfig(LoggingSettings())

        assert "deprecated" not in capsys.readouterr().err


class TestLoggingSettings:
    def test_output_format_is_case_insensitive(self, monkeypatch, no_format_env):
        monkeypatch.setenv("DIAL_SDK_LOG_FORMAT", "JSON")

        assert LoggingSettings().log_output_format == "json"

    def test_invalid_output_format_is_rejected(self, monkeypatch, no_format_env):
        monkeypatch.setenv("DIAL_SDK_LOG_FORMAT", "yaml")

        with pytest.raises(ValidationError):
            LoggingSettings()

    def test_json_template_is_parsed_from_env(self, monkeypatch, no_format_env):
        monkeypatch.setenv("DIAL_SDK_JSON_LOG_FORMAT", '{"m": "%(message)s"}')

        assert LoggingSettings().json_log_format == {"m": "%(message)s"}

    def test_default_json_template_keeps_tracebacks(self, no_format_env):
        assert LoggingSettings().json_log_format["exception"] == "%(exc_text)s"

    def test_deprecated_vars_are_detected(self, monkeypatch, no_format_env):
        monkeypatch.setenv("LOG_FORMAT", "%(message)s")
        monkeypatch.setenv("LOG_DATE_FORMAT", "%H:%M")

        assert LoggingSettings().deprecated_format_vars_set == (
            "LOG_FORMAT",
            "LOG_DATE_FORMAT",
        )

    def test_no_deprecated_vars_by_default(self, no_format_env):
        assert LoggingSettings().deprecated_format_vars_set == ()
