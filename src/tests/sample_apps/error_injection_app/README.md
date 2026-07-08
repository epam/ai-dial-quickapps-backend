# Error-injection sample model

A tiny standalone **DIAL chat-completion** app (built on `aidial-sdk`) whose only job is
to **deterministically reproduce every failure mode** that QuickApps' error resolver
(`src/quickapp/core/application/_exception_message_resolver.py`) distinguishes.

Register it in DIAL Core as a model, wire it as a QuickApp's **orchestrator deployment**,
and use DIAL Chat conversation-starter buttons to trigger each scenario with one click.
It is **not** a pytest and never runs as part of `make test`.

Deployment name: **`error-injection-model`** (see `DEPLOYMENT_NAME`).

## Files

| File | Purpose |
|---|---|
| `error_injection_app.py` | Runnable entry point: assembles the `DIALApp` and runs uvicorn. |
| `completion.py` | The `ErrorInjectionModel` (`ChatCompletion` subclass) and the pre-/mid-stream error mechanics. |
| `scenarios.py` | The scenario registry (`SCENARIOS`), the `Scenario` model, trigger matching, and tunable constants. |
| `sample_quickapp_config.json` | Minimal, schema-valid QuickApp manifest with a conversation starter per trigger. |

## How it works

The app reads the **last user message**, matches it (case-insensitive substring, longest
trigger wins) against a scenario registry (`_SCENARIOS`), and reproduces that scenario.
Unmatched messages stream a help text listing all triggers.

Two error-delivery shapes are reproduced (verified against `aidial-sdk` 0.32.0):

- **Pre-stream errors** are raised *before* any chunk is emitted. The SDK returns a
  **non-200 JSON** body `{"error": {...}}` with the exception's `status_code`.
- **Mid-stream errors** are raised *after* a choice is opened and content appended. The
  HTTP response is already committed as `200 text/event-stream`, so the error is
  delivered as an **SSE `data: {"error": ...}` chunk** appended to the live stream.
  DIAL Chat surfaces **only `display_message`** on the mid-stream path.

> Note: in **non-streaming** mode the SDK cannot commit a partial stream, so mid-stream
> scenarios also come back as a non-200 error. Trigger behaviour matches the table below
> when the caller uses `stream: true` — which QuickApps' orchestrator always does.

## Run it

From the repo root (`ai-dial-quickapps-backend/`):

```bash
poetry run python src/tests/sample_apps/error_injection_app/error_injection_app.py
```

Listens on `0.0.0.0:5002` by default. Override with env vars:

| Env var | Default | Purpose |
|---|---|---|
| `ERROR_INJECTION_APP_HOST` | `0.0.0.0` | Bind host |
| `ERROR_INJECTION_APP_PORT` | `5002` | Bind port |

The "slow response" delay is the module constant `SLOW_SCENARIO_DELAY_SECONDS` in
`scenarios.py` (default 30s) — edit it to comfortably exceed your client's read timeout.

Endpoints (added by the SDK):

- `POST /openai/deployments/error-injection-model/chat/completions`
- `GET  /health`

### Quick manual check

The SDK requires an `Api-Key` header on every request (DIAL Core forwards it in real
use; for manual curl any non-empty value works).

```bash
# Pre-stream error -> non-200 JSON body {"error": {...}}
curl -i -X POST \
  http://localhost:5002/openai/deployments/error-injection-model/chat/completions \
  -H 'Content-Type: application/json' -H 'Api-Key: dummy' \
  -d '{"stream": true, "messages": [{"role": "user", "content": "pre-stream 500"}]}'

# Mid-stream error -> HTTP 200 SSE with content then a data: {"error": ...} chunk
curl -N -X POST \
  http://localhost:5002/openai/deployments/error-injection-model/chat/completions \
  -H 'Content-Type: application/json' -H 'Api-Key: dummy' \
  -d '{"stream": true, "messages": [{"role": "user", "content": "mid-stream error"}]}'
```

## Register it in DIAL Core as a model

Add a model entry to your DIAL Core config that proxies to this server. Example
(`core/configuration` style):

```json
{
  "models": {
    "error-injection-model": {
      "type": "chat",
      "displayName": "Error Injection Model",
      "endpoint": "http://<host-reachable-from-core>:5002/openai/deployments/error-injection-model/chat/completions"
    }
  }
}
```

Use a host/port reachable from DIAL Core (e.g. a container name in docker-compose, or
`host.docker.internal:5002` when Core runs in Docker and this server on the host).

## Wire it as a QuickApp orchestrator

Point the QuickApp manifest's `orchestrator.deployment.deployment_id` at the DIAL Core
model id above. A minimal, schema-valid manifest is provided in
[`sample_quickapp_config.json`](./sample_quickapp_config.json) — it also defines a
conversation starter per trigger phrase so a tester can one-click each scenario:

```json
{
  "orchestrator": {
    "deployment": { "deployment_id": "error-injection-model" },
    "system_prompt": { "type": "custom", "variables": {}, "content": "..." }
  },
  "contexts": [],
  "tool_sets": [],
  "conversation_starters": { "starters": [ { "title": "...", "text": "happy path" } ] }
}
```

## Trigger phrases

Each conversation starter sends the **text** below; the model matches it and produces the
listed behaviour. Values are what a QuickApp tester sees in DIAL Chat.

| Trigger text | Delivery | Status / code | What DIAL Chat shows |
|---|---|---|---|
| `happy path` | 200 stream | — | A normal streamed answer (control case) |
| `pre-stream 500` | non-200 | 500 | `display_message`: "The upstream provider is temporarily unavailable." |
| `content filter` | non-200 | 400 / `content_filter` | Content-policy message: "…blocked by the content management policy. Please rephrase your message." |
| `context length exceeded` | non-200 | 400 / `context_length_exceeded` | "…exceeds the maximum context length… Please shorten your messages and try again." |
| `rate limit` | non-200 | 429 | `display_message`: "Too many requests right now. Please slow down." |
| `auth failed` | non-200 | 401 | Authentication-failed message (contact administrator) |
| `permission denied` | non-200 | 403 | No-permission message (contact administrator) |
| `not found` | non-200 | 404 | Model-not-found message (contact administrator) |
| `payload too large` | non-200 | 413 | Payload-too-large message |
| `invalid request` | non-200 | 422 | Invalid-request message (contact administrator) |
| `internal error` | non-200 | 500 (no `display_message`) | Generic internal-error message + "Please try again later." |
| `mid-stream error` | 200 stream + SSE error | 500 | Partial text, then `display_message`: "The model failed while responding." |
| `stream failure` | 200 stream + SSE error | 500 (no `display_message`) | Partial text, then generic stream-failure message + "Please try again later." |
| `uncaught exception` | non-200 | 500 (SDK-wrapped `RuntimeError`) | Generic internal-error message + "Please try again later." |
| `slow response` | 200 stream (delayed) | — | A token, a long pause (`SLOW_SCENARIO_DELAY_SECONDS`), then completion — exercises client timeouts |

> **Key distinction:** pre-stream errors arrive as a **non-200 response** (no content was
> streamed); mid-stream errors arrive as an **SSE error chunk inside a committed 200
> stream** (after visible partial content). QuickApps' resolver handles both; only
> `display_message` reaches the user on the mid-stream path.

## Extending

Append a new `Scenario` to `SCENARIOS` in `scenarios.py` (and a matching conversation
starter in `sample_quickapp_config.json`). If it needs behaviour beyond the existing
`ScenarioKind` variants, add a branch in `ErrorInjectionModel._run_scenario`
(`completion.py`). No other wiring is needed.
