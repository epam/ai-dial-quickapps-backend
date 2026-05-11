import logging

import uvicorn.logging


class OtelAwareFormatter(uvicorn.logging.DefaultFormatter):
    """Render the OTEL trace block only when a real trace is active.

    LoggingInstrumentor (enabled by aidial-sdk when OTEL_PYTHON_LOG_CORRELATION=true)
    stamps `otelTraceID` / `otelSpanID` / `otelServiceName` / `otelTraceSampled`
    onto every LogRecord. With no active span the trace ID is the literal string
    "0"; when the instrumentor never ran the attribute is absent. In both cases,
    suppress the block to keep logs readable.
    """

    def formatMessage(self, record: logging.LogRecord) -> str:
        trace_id = getattr(record, "otelTraceID", None)
        if trace_id and trace_id != "0":
            record.otel_context = (
                f"[trace_id={trace_id} "
                f"span_id={getattr(record, 'otelSpanID', '0')} "
                f"resource.service.name={getattr(record, 'otelServiceName', '')} "
                f"trace_sampled={getattr(record, 'otelTraceSampled', False)}] | "
            )
        else:
            record.otel_context = ""
        return super().formatMessage(record)
