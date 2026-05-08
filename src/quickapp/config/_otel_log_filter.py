import logging


class OtelDefaultsFilter(logging.Filter):
    """Ensures OTEL trace fields exist on every LogRecord.

    The opentelemetry LoggingInstrumentor injects these via a custom record
    factory, but only when OTEL_PYTHON_LOG_CORRELATION=true. When telemetry
    is off, the formatter must still render — fall back to neutral values.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # LoggingInstrumentor's record factory sets all four fields together,
        # so a single hasattr is enough to short-circuit when telemetry is on.
        if hasattr(record, "otelTraceID"):
            return True
        record.otelTraceID = "0"
        record.otelSpanID = "0"
        record.otelServiceName = ""
        record.otelTraceSampled = False
        return True
