# Logging

Quick Apps logs to the console (stderr) through the standard `logging` module, wired by
`LoggingConfig` on top of [aidial-sdk's logging support](https://github.com/epam/ai-dial-sdk/blob/development/docs/logging.md):
a single console handler lives on the root logger, and every managed logger (`quickapp`, `uvicorn*`,
`httpx`, `httpcore`, `openai`, `aidial_sdk`) propagates to it. Everything is configured through
environment variables.

## Levels

| Variable             | Default | Scope                                                                                     |
|----------------------|---------|-------------------------------------------------------------------------------------------|
| `LOG_LEVEL`          | `INFO`  | Root logger and managed third-party loggers (`uvicorn*`, `httpx`, `httpcore`, `openai`, `aidial_sdk`). |
| `QUICKAPP_LOG_LEVEL` | `INFO`  | The application's own `quickapp.*` loggers.                                                |

## Payload content

Logs carry structure, not content: message bodies, tool-call arguments, and response bodies are
never logged at any level. The `LOG_PAYLOADS` switch (local development only) routes truncated
payload detail through dedicated DEBUG records, and while it is off the payload-capable third-party
loggers (`openai`, `httpx`, `httpcore`) are capped at INFO regardless of `LOG_LEVEL`. See
[Payload Logging](../README.md#payload-logging) in the README for the switch reference.

## Output format

`DIAL_SDK_LOG_FORMAT` selects the console format: `text` (default, human-readable) or `json`
(machine-readable, one record per line). The variable is shared with aidial-sdk, so the SDK's own
early records — emitted before `LoggingConfig` runs — use the same format.

### Text (default)

The built-in format is rendered by `OtelAwareFormatter` (a uvicorn `DefaultFormatter` subclass):

```
%(levelprefix)s | %(asctime)s | %(process)d | %(name)s | %(otel_context)s%(message)s
```

`%(otel_context)s` is synthesized: when a trace is active it renders a
`[trace_id=… span_id=… resource.service.name=… trace_sampled=…] | ` block, otherwise it collapses
to nothing (see [Trace correlation](#trace-correlation)).

To customize, set `DIAL_SDK_TEXT_LOG_FORMAT` to a Python `logging`
[`%`-style](https://docs.python.org/3/library/logging.html#logrecord-attributes) format string:

```sh
DIAL_SDK_TEXT_LOG_FORMAT='%(levelprefix)s | %(asctime)s | %(name)s | %(message)s'
```

Custom formats are rendered by the SDK's text formatter, which does not synthesize
`%(otel_context)s`. Reference the raw `otel*` fields instead — and only when tracing is guaranteed
to be on: the text formatter has no missing-field fallback, so a format referencing an absent field
drops the record.

### JSON

```sh
DIAL_SDK_LOG_FORMAT=json
```

Each record renders as one line of valid JSON — values (including messages with quotes or newlines,
and tracebacks) are escaped via `json.dumps`. The default template ships these fields:

```json
{"level": "INFO", "time": "2026-07-20 15:12:43", "logger": "quickapp.core.agent", "process": "42", "message": "hello", "exception": ""}
```

`exception` carries the formatted traceback for `logger.exception(...)` records and is empty
otherwise. Any `otel*` trace fields present on the record are appended automatically.

To customize, set `DIAL_SDK_JSON_LOG_FORMAT` to a JSON document whose string leaves are `%`-style
format strings (nesting works, values are escaped):

```sh
DIAL_SDK_JSON_LOG_FORMAT='{"lvl": "%(levelname)s", "msg": "%(message)s", "err": "%(exc_text)s"}'
```

An overriding template fully replaces the default — keep a `%(exc_text)s` leaf, or tracebacks will
be dropped from the output.

### Deprecated: `LOG_FORMAT` and `LOG_DATE_FORMAT`

These predate the SDK-aligned variables. They are still honored — and, when set, win over
`DIAL_SDK_TEXT_LOG_FORMAT` so existing deployments keep their output — but a warning is emitted at
startup and support will be removed in a future release. Setting either variable selects the legacy
formatter path as a whole: e.g. `LOG_DATE_FORMAT` alone combines with the built-in default format,
not with `DIAL_SDK_TEXT_LOG_FORMAT`. Don't mix old and new variables.

- `LOG_FORMAT` → use `DIAL_SDK_TEXT_LOG_FORMAT` (or switch to `DIAL_SDK_LOG_FORMAT=json`).
- `LOG_DATE_FORMAT` → no successor; the timestamp format is fixed to `%Y-%m-%d %H:%M:%S` (the
  previous default) going forward.

## Trace correlation

When tracing is enabled (`OTEL_TRACES_EXPORTER=otlp` with a reachable
`OTEL_EXPORTER_OTLP_ENDPOINT`), OpenTelemetry's logging instrumentor stamps `otelTraceID`,
`otelSpanID`, `otelServiceName`, and `otelTraceSampled` onto every record. The default text format
renders them through the conditional `%(otel_context)s` block; JSON output appends them
automatically.

> [!WARNING]
> `OTEL_PYTHON_LOG_CORRELATION=true` is deprecated by aidial-sdk: it double-logs SDK records and
> suppresses the console handler this service installs, so none of the formatting above applies.
> Remove it from deployments — trace fields are injected whenever tracing is on.

## OTLP log export

With `OTEL_LOGS_EXPORTER=otlp`, aidial-sdk attaches an OTLP export handler to the root logger.
Because every managed logger propagates to root, the exported records match the console output
record-for-record. Console formatting does not apply to exported records — they travel as
structured attributes.
