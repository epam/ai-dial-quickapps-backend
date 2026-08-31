<h1 align="center">
         Quick Apps (2.0)
    </h1>
    <p align="center">
        <p align="center">
        <a href="https://dialx.ai/">
          <img src="https://dialx.ai/logo/dialx_logo.svg" alt="About DIALX">
        </a>
    </p>
<h4 align="center">
    <a href="https://discord.gg/ukzj9U9tEe">
        <img src="https://img.shields.io/static/v1?label=DIALX%20Community%20on&message=Discord&color=blue&logo=Discord&style=flat-square" alt="Discord">
    </a>
</h4>

Quick Apps (2.0) is a composer for building DIAL applications from reusable tools and integrations. It lets you
declaratively compose new DIAL applications by wiring DIAL-native tools, REST APIs, and MCP servers with any LLM
registered in DIAL Core acting as the orchestrator. Publishing a Quick App produces a DIAL application record managed by
Core.

## Quick highlights

- Compose applications by wiring tools and an LLM orchestrator via JSON-schema–validated manifests.
- Advanced flow controls: fallbacks, parallel tool execution, loops and retries.
- Native DIAL tools plus external REST and MCP integrations.
- Any LLM available in DIAL Core (Azure OpenAI, Anthropic, Vertex AI, etc.).

## Feature Lifecycle

Some features are released as **Preview** before becoming **Stable**:

| Stage       | Meaning                                                                                              |
|-------------|------------------------------------------------------------------------------------------------------|
| **Preview** | Available for use but may change in breaking ways without a major version bump. Feedback is welcome. |
| **Stable**  | Covered by semantic versioning — breaking changes require a major version bump.                      |

Features in Preview are marked with a `[Preview]` tag in documentation.

## Documentation

- [Configuration Reference](./CONFIGURATION.md) - Full configuration model, environment variables, and examples
- [Agent Skills](docs/skills.md) - How to create and manage reusable agent skills
- [Config-Driven Hooks](docs/designs/config_driven_hooks.md) `[Preview]` - Declarative synthetic tool call injection at orchestrator seams
- [Technical Documentation](./docs/README.md) - Internal architecture and design documents

## Quick start (general)

- Local development and run instructions, utilities and tests remain in this repository. For detailed setup commands (
  venv, poetry, make targets) see the project docs and Makefile.
- To run Quick Apps as a standalone service you need to provide DIAL Core endpoint and relevant environment variables.

## Configuration

All configuration-specific details (configuration model, environment variables, orchestrator, contexts, tool_sets, tool
fallback, attachments, authorization types, parameter/display configurations and examples) were moved to a dedicated
file:

- [Configuration](./CONFIGURATION.md) — full configuration reference and examples.

### Hooks `[Preview]`

Hooks let you pre-populate the agent's message history with synthetic tool call results — without writing Python code. Each hook fires at a named orchestrator seam and injects a `(ASSISTANT/tool_calls, TOOL)` message pair.

Enable with `ENABLE_PREVIEW_FEATURES=true`, then add a `hooks` array to the app manifest:

```json
{
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_request_start",
      "toolset_name": "memory_server",
      "tool_name": "get_memories",
      "arguments": { "user_id": "123" },
      "frequency": "always"
    }
  ]
}
```

Key fields:

| Field | Description |
|---|---|
| `kind` | Hook type. Only `"tool_call"` is supported today. |
| `event` | Orchestrator seam. Only `"on_request_start"` is wired today. |
| `toolset_name` | Toolset prefix for REST API / MCP tools. Omit for DIAL Deployment and Internal tools. |
| `tool_name` | Tool name within the toolset, or the exact function name when `toolset_name` is omitted. |
| `arguments` | Arguments forwarded to the tool call. |
| `frequency` | `"always"` — inject on every request. `"append_if_changed"` (default) — inject only when the result differs from the last injection. |

See [Config-Driven Hooks design doc](docs/designs/config_driven_hooks.md) for the full reference.

### Forwarding headers

Incoming request headers whose names start with `X-` (case-insensitive) are automatically forwarded to all outbound
calls made during that chat completion. No configuration is required.

- **Orchestrator (Azure OpenAI):** forwarded headers are sent on each chat completion request.
- **MCP tools:** forwarded headers are merged into the HTTP/SSE headers used when connecting to MCP servers.
- **DIAL deployment tools:** forwarded headers are sent as `extra_headers` when calling DIAL chat completions.
- **REST API tools:** forwarded headers are merged into the outgoing HTTP request headers.

Use this for tracing (e.g. `X-Request-Id`, `X-Correlation-Id`), multi-tenancy (`X-Tenant-Id`), or any custom header
your gateways or downstream services expect.

### Stage display level

Controls which tool-execution stages are surfaced in the DIAL UI for each app. Set `features.stage_display.level` in the app manifest:

| Value | Behavior |
|---|---|
| `none` | No stages shown at all, not even for errors |
| `error` | Show stages only for failed tool calls |
| `info` | Show stages for regular tool calls and errors (default) |
| `debug` | Show stages for all tool calls, including internal/system ones |

```json
{
  "features": {
    "stage_display": {
      "level": "debug"
    }
  }
}
```

### Environment Variables

| Variable                                   | Default                    | Required | Description                                                                                                  |
|--------------------------------------------|----------------------------|----------|--------------------------------------------------------------------------------------------------------------|
| **DIAL Core**                              |                            |          |                                                                                                              |
| `DIAL_URL`                                 | —                          | Yes      | URL of the DIAL Core API                                                                                     |
| `DIAL_API_VERSION`                         | `2025-01-01-preview`       | No       | API version for DIAL Core API                                                                                |
| `APP_SCHEMA_ID`                            | `https://mydial.epam.com/custom_application_schemas/quickapps2` | No | Full application type schema `$id` emitted in the generated app schema. When unset, the built-in default is used. |
| **Proxy**                                  |                            |          |                                                                                                              |
| `PROXY_LANGUAGE_HEADER`                    | `accept-language`          | No       | Name of the incoming HTTP request header that carries the locale for UI display (stage name localization). Override when a reverse proxy rewrites the standard `Accept-Language` header before forwarding the request. |
| **Logging**                                |                            |          |                                                                                                              |
| `DIAL_SDK_LOG_FORMAT`                      | `text`                     | No       | Console log output format: `text` (human-readable) or `json` (escape-safe, one record per line). See [docs/logging.md](docs/logging.md). |
| `DIAL_SDK_TEXT_LOG_FORMAT`                 | [see docs/logging.md](docs/logging.md) | No | Custom `%`-style format string for `text` output. Unset (default) keeps the built-in format with the conditional OTEL trace block. |
| `DIAL_SDK_JSON_LOG_FORMAT`                 | [see docs/logging.md](docs/logging.md) | No | Custom template for `json` output — a JSON document whose string leaves are `%`-style format strings, values escaped via `json.dumps`. |
| `LOG_LEVEL`                                | `INFO`                     | No       | Root logger level (all loggers except quickapp)                                                              |
| `QUICKAPP_LOG_LEVEL`                       | `INFO`                     | No       | Log level for quickapp loggers                                                                               |
| `LOG_PAYLOADS`                             | `false`                    | No       | Emit payload content (message bodies, tool-call arguments, tool/LLM response bodies) at DEBUG. When `false`, no payload content is logged at **any** level and the payload-capable third-party loggers (`openai`/`httpx`/`httpcore`) are capped at INFO. **Local development only** — see [Payload Logging](#payload-logging). |
| `LOG_PAYLOADS_MAX_LENGTH`                  | `2000`                     | No       | Per-field character cap applied to each payload value when `LOG_PAYLOADS=true`; longer values are truncated. Inert when `LOG_PAYLOADS=false`. |
| **Agent**                                  |                            |          |                                                                                                              |
| `DEFAULT_AGENT_MAX_ITERATIONS`             | `15`                       | No       | Maximum number of orchestrator iterations (`-1` for infinite)                                                |
| `DEFAULT_ORCHESTRATOR_DEPLOYMENT_ID`       | —                          | No       | Default DIAL deployment id used as the orchestrator model when a QuickApp manifest omits `orchestrator.deployment`. Also surfaces as the JSON-schema `default` for that field so DIAL Core can pre-fill new manifests. Apps can override per-app. |
| `SHOW_USAGE_STATISTICS`                    | `false`                    | No       | Include usage statistics in chat completion stream                                                           |
| `SHOW_EXECUTION_TIME_STAGE`                | `false`                    | No       | Show execution time stage in the UI                                                                          |
| **Python Interpreter**                     |                            |          |                                                                                                              |
| `PY_INTERPRETER_LOCAL_RUN`                 | `false`                    | No       | Run PyInterpreter locally instead of via DIAL Core API                                                       |
| `PY_INTERPRETER_URL`                       | *(falls back to DIAL_URL)* | No       | URL of the PyInterpreter service                                                                             |
| `PY_INTERPRETER_API_KEY`                   | —                          | No       | API key for local-run PyInterpreter                                                                          |
| `PY_INTERPRETER_DEFAULT_SESSION_ID`        | —                          | No       | Default session ID for the PyInterpreter                                                                     |
| `PY_INTERPRETER_CLIENT_MAX_RETRIES`        | `3`                        | No       | Max retries for PyInterpreter client requests                                                                |
| **Tool Timeouts**                          |                            |          |                                                                                                              |
| `DEFAULT_TOOL_TIMEOUT_SECONDS`             | `300.0`                    | No       | Deployment-wide default timeout (seconds, `0 < x ≤ 3600`) applied to every tool call (deployment, REST API, MCP, Python interpreter). Apps can override per-app via `tool_defaults.timeout_seconds`. |
| `DEFAULT_FILE_LOADING_SIZE_LIMIT`          | `10485760`                 | No       | Deployment-wide default maximum size (in bytes) for files the agent downloads. Apps can override per-app via `features.file_loading.size_limit`. |
| **Stage Display**                          |                            |          |                                                                                                              |
| `DEFAULT_STAGE_DISPLAY_LEVEL`              | —                          | No       | Deployment-wide override for stage visibility threshold (`none`, `error`, `info`, `debug`; case-insensitive). When set, wins over every app's `features.stage_display.level`. Unset (default) defers to the per-app config, which defaults to `info`. |
| **DIAL Files — Tool-Response Offload**     |                            |          |                                                                                                              |
| `TOOL_CALL_RESULT_OFFLOAD__ENABLED_BY_DEFAULT` | `true`                 | No       | Default value of the per-app `enabled` flag (`features.dial_files.tool_call_result_offload.enabled`). Apps override per-app; `enabled: false` disables offload for that app. |
| `TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD` | `40000`                    | No       | Default byte threshold above which a tool-call response is offloaded to a DIAL file. Apps override per-app via `features.dial_files.tool_call_result_offload.size_threshold`. |
| `TOOL_CALL_RESULT_OFFLOAD__EXCLUDED_TOOLS` | `[]`                       | No       | Default JSON list of **additional** tool names exempt from offloading. The read-back tools (`internal_file_read_lines`, `internal_file_search`) are always excluded regardless of this value, so a large read-back slice is never re-offloaded. Apps add more per-app via `features.dial_files.tool_call_result_offload.excluded_tools`. |
| **External URL Egress**                    |                            |          |                                                                                                              |
| `EXTERNAL_URL_FETCH_ENABLED`                 | `false`                    | No       | Admin cap on fetching external (non-DIAL) URLs. When `false` (default), no app may fetch external URLs regardless of its manifest; the deployment-handoff branch (deployments with `features.url_attachments`) is unaffected. Apps can opt out per-app via `features.external_url_fetch.enabled=false` even when the admin allows. |
| `EXTERNAL_URL_FETCH_HOST_ALLOWLIST`        | —                          | No       | Comma-separated allowlist of host patterns for external URL fetches. Unset (default) means no admin-level host restriction. Patterns: exact host (`example.com`) or `*.example.com` for any subdomain. Re-checked on every redirect hop. Per-app `features.external_url_fetch.host_allowlist` narrows further (intersection) but never expands. |
| `EXTERNAL_URL_FETCH_MAX_REDIRECTS`         | `5`                        | No       | Maximum HTTP redirects on external URL fetches. Each hop is SSRF-checked. Hard ceiling 10.                   |
| `EXTERNAL_URL_FETCH_CONNECT_TIMEOUT_SECONDS` | `5.0`                    | No       | TCP connect timeout (seconds) for external URL fetches. Read/write/pool timeouts use the resolved tool timeout. |
| **Skills**                                 |                            |          |                                                                                                              |
| `DIAL_SKILLS_FILE_MAX_BYTES`               | `262144`                   | No       | Cap on a single file read from a DIAL skill resource, `SKILL.md` included. Must exceed the largest manifest you expect: an over-cap manifest drops the skill. See [docs/skills.md](docs/skills.md). |
| `DIAL_SKILLS_MAX_FILES`                    | `200`                      | No       | Maximum bundled files advertised to the agent per DIAL skill resource; beyond it the listing is truncated     |
| `DIAL_SKILLS_LISTING_MAX_PAGES`            | `10`                       | No       | Maximum file-listing pages followed per DIAL skill resource, bounding a server-supplied cursor                |
| **Feature Gating**                         |                            |          |                                                                                                              |
| `ENABLE_PREVIEW_FEATURES`                  | `false`                    | No       | Enable preview features across the deployment (schema visibility + runtime activation)                       |
| **Templates**                              |                            |          |                                                                                                              |
| `PREDEFINED_EXTRA_PATHS`                   | —                          | No       | JSON list of directories layered on top of built-in predefined content (later entries override earlier ones) |
| `CONFIG_PROMPT_MAPPING`                    | *(built-in mapping)*       | No       | JSON mapping of predefined system prompts to DIAL Core deployments                                           |
| **Observability**                          |                            |          |                                                                                                              |
| `OTEL_SERVICE_NAME`                        | `quickapps`                | No       | Service name stamped on all exported telemetry (traces, metrics, logs)                                       |
| `OTEL_TRACES_EXPORTER`                     | —                          | No       | Set to `otlp` to enable tracing and export spans over OTLP/gRPC. Instruments the FastAPI server and outgoing HTTP clients (`httpx`, `requests`, `aiohttp`, `urllib`) and stamps trace context onto log records — see [docs/logging.md](docs/logging.md). |
| `OTEL_METRICS_EXPORTER`                    | —                          | No       | Comma-separated metric exporters: `otlp` (push over OTLP/gRPC) and/or `prometheus` (serve a scrape endpoint). Enables FastAPI and system/process metrics.  |
| `OTEL_LOGS_EXPORTER`                       | —                          | No       | Set to `otlp` to export log records (INFO and above) over OTLP/gRPC alongside console output — see [docs/logging.md](docs/logging.md). |
| `OTEL_EXPORTER_OTLP_ENDPOINT`              | `http://localhost:4317`    | No       | OTLP/gRPC collector endpoint shared by trace, metric, and log export. One of the [standard OpenTelemetry SDK variables](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/), which the underlying exporters honor as usual (per-signal endpoints, headers, timeouts, resource attributes, …). |
| `OTEL_EXPORTER_PROMETHEUS_PORT`            | `9464`                     | No       | Port of the Prometheus scrape endpoint (effective only with `prometheus` in `OTEL_METRICS_EXPORTER`)         |
| **Scripts & Tests**                        |                            |          |                                                                                                              |
| `REMOTE_DIAL_URL`                          | —                          | No       | URL of the remote DIAL Core, used only by `generate_dial_config` script and e2e/integration tests            |
| `REMOTE_DIAL_API_KEY`                      | —                          | No       | API key of the remote DIAL Core, used only by `generate_dial_config` script and e2e/integration tests        |

#### Deprecated Environment Variables

> [!CAUTION]
> These variables still work but will be removed in a future major version.

| Variable                        | Replacement                                                        | Description                                                                                                                  |
|---------------------------------|--------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| `PREDEFINED_BASE_PATH`          | `PREDEFINED_EXTRA_PATHS`                                           | If set alone, treated as a single extra layer on top of the built-in content                                                 |
| `PY_INTERPRETER_CLIENT_TIMEOUT` | `DEFAULT_TOOL_TIMEOUT_SECONDS` or `tool_defaults.timeout_seconds`  | When set, still controls the PyInterpreter client timeout (seconds, default `60.0`), but the unified tool-timeout settings are preferred. |
| `LOG_FORMAT`                    | `DIAL_SDK_TEXT_LOG_FORMAT` or `DIAL_SDK_LOG_FORMAT=json`           | When set, still controls the `text` output format (and wins over the replacements); a warning is emitted at startup. See [docs/logging.md](docs/logging.md). |
| `LOG_DATE_FORMAT`               | —                                                                  | Still honored alongside `LOG_FORMAT`; going forward the timestamp format is fixed to `%Y-%m-%d %H:%M:%S` (the previous default). |
| `OTEL_PYTHON_LOG_CORRELATION`   | — *(automatic)*                                                    | Deprecated by aidial-sdk; a warning is emitted at startup. Trace fields are stamped onto log records whenever tracing is enabled, so the switch is redundant — and setting it installs OTel's legacy root-logger format, which double-logs SDK records and bypasses this service's console formatting. See [docs/logging.md](docs/logging.md). |

**Notes:**

- Variables listed above are a superset used across development and deployment modes. Some variables (e.g.
  `REMOTE_DIAL_*`) are only used when running the full local stack via docker-compose or during testing.
- Telemetry is opt-in: when none of `OTEL_TRACES_EXPORTER` / `OTEL_METRICS_EXPORTER` / `OTEL_LOGS_EXPORTER`
  is set, OpenTelemetry is not initialized at all.
- For a standalone Quick Apps deployment the essential variable is only `DIAL_URL`
- For PyInterpreter tool setup
  see: [DIAL Core](https://github.com/epam/ai-dial-core), [PyInterpreter](https://github.com/epam/ai-dial-code-interpreter).

#### Log Format Configuration

Moved to [docs/logging.md](docs/logging.md), which covers the text and JSON output modes, format
customization, OTEL trace correlation, and OTLP log export.

#### Payload Logging

By policy, logs carry **structure** — roles, counts, sizes, names, ids, statuses, durations, HTTP codes,
header **names**, and URLs stripped to scheme/host/path — and never **content**: message bodies, tool-call
argument values, tool/LLM response bodies, attachment content, header **values**, or URL query strings. This
holds at every level, DEBUG included, so raising verbosity during an incident never brings conversation
content into the logs.

`LOG_PAYLOADS=true` is the single, explicit exception: it re-enables the payload-bearing DEBUG records (message
context, tool-call arguments, raw responses), each field truncated to `LOG_PAYLOADS_MAX_LENGTH`, and lifts the
INFO cap on the wire-level third-party loggers (`openai`, `httpx`, `httpcore`). Every payload record is prefixed
with a `[payload]` marker so these lines can be found — or excluded — with a single filter. Forwarded header **values** are
never logged, even with the switch on. The switch is additive to the level — content appears only when
`QUICKAPP_LOG_LEVEL=DEBUG` **and** `LOG_PAYLOADS=true`.

> [!CAUTION]
> `LOG_PAYLOADS` is intended for **local development only**. It writes conversation content and wire-level
> third-party payloads to the log pipeline (including any OTLP export). Do **not** enable it in shared or
> production environments.

## Local Development

### Pre-requisites

1. Install Make
    - macOS: usually preinstalled.
    - Windows: see https://gnuwin32.sourceforge.net/packages/make.htm or use Chocolatey.
    - Ensure `make` is in PATH (`which make`).

2. Install Python 3.13
    - macOS (Homebrew): `brew install python@3.13`
    - Official downloads: https://www.python.org/downloads/
    - Ensure `python3.13` (or `python3`) is in PATH (`python3.13 --version`).

3. Recommended way - system-wide, independent of any particular python venv:

    - MacOS - recommended way to install poetry is to [use pipx](https://python-poetry.org/docs/#installing-with-pipx)
    - Windows - recommended way to install poetry is to
      use [official installer](https://python-poetry.org/docs/#installing-with-the-official-installer)
    - Make sure that `poetry` is in the PATH and works properly (run `poetry --version`).
    - Alternative - venv-specific (using `pip`):
      make sure the correct python venv is activated `make install_poetry`

### Setup

1. Clone the repository
2. Create and activate virtual environment

    ```bash
    make init_venv
    source .venv/bin/activate
    ```

3. Install dev dependencies

    ```bash
    make install_dev
    ```

4. Create `.env` file in the root of the project. Copy `.env.template` file data to the `.env` and fill the values. The
   full information about ENV variables can be found in [Configuration](./CONFIGURATION.md).

     ```bash
     cp .env.template .env
     ```

5. Generate DIAL configuration files:

    ```bash
    make generate_dial_config
    ```

   This command will generate two files in `docker_compose_files/core/configuration/generated/`:
    - `models.json` - contains the models configuration for DIAL.

### Run

- Option A — Full local stack (docker-compose)
    - Use this if you want to bring up DIAL Core, chat UI, redis, themes and adapters locally for end-to-end development
      and testing.
    - This docker-compose setup launches multiple services and uses internal hostnames (for example core, redis,
      themes).
    - Setup expects the Quick Apps service to run on your host machine at `host.docker.internal:5000`

      ```bash
      python3 ./src/quickapp/app.py
      ```

    - Then start the local stack:

      ```bash
      docker compose up -d
      ```

    - Optional — DIAL Admin (UI + backend API, embedded H2 database):

      ```bash
      docker compose --profile admin up -d
      ```

      Or uncomment `COMPOSE_PROFILES=admin` in `.env` and run `docker compose up -d` as usual.

      Startup order: `admin-export-init` → `redis` / `core` (healthy) → `admin-backend` (healthy) → `admin-frontend`.

      - Admin UI: http://localhost:3020 (unauthenticated — only `DIAL_ADMIN_API_URL` + `NEXTAUTH_SECRET`; do not set `NEXTAUTH_URL` or any `AUTH_*` vars)
      - Admin API: http://localhost:8092
      - Backend uses H2 with dev encryption keys; Core access via `dial_api_key`. Not production-equivalent.
      - **Admin → Core sync:** `admin-export-init` creates `docker_compose_files/core/admin-export/out.json` (gitignored) before Core starts. Admin exports merged config there (~15s after changes) and calls Core reload (`ENABLE_CONFIG_RELOAD`). Core loads static JSON from `docker_compose_files/core/configuration/` plus `out.json` (last), so Admin UI edits override the static files. Allow ~20s after a save for export + reload.
      - Populate Admin H2 initially via the Admin UI import flow, or keep an existing `admin-backend-data` volume. Core static config is not auto-imported into Admin on startup.

    - Notes:
        - If you want to run Quick Apps in Docker instead of on the host, update
          [application-schemas.json](docker_compose_files/core/configuration/application-schemas.json) and change the Quick
          Apps host from `host.docker.internal:5000` to `quick-apps:5000`.
        - When running via docker-compose the compose files set service hostnames (for example DIAL URL inside
          containers is http://core:8080). Those container-internal hostnames are not valid from your host machine — use
          the exposed ports (for example http://localhost:8090) when calling services from the host.
        - Some environment variables in the repo (e.g. adapter or chat-specific variables) are only relevant for the
          full stack docker-compose setup and may be ignored when you deploy Quick Apps standalone.

- Option B — Quick Apps standalone (connect to an existing DIAL Core)
    - Use this when you already have a DIAL Core instance available (local, staging, or cloud). You do NOT need to run
      core, chat, redis, themes, or adapter containers to deploy Quick Apps.
    - Steps:
        1. Create and fill your .env (or set environment variables) with the fields required by Quick Apps. At minimum
           ensure:
            - DIAL_URL points to your DIAL Core API endpoint (example: https://core.example.com or http://core:8080
              depending on your environment).
            - If required by your DIAL Core instance, set DIAL_API_KEY or other auth variables.
            - PREDEFINED_EXTRA_PATHS if you need to add or override predefined templates/toolsets.
        2. Run the Quick Apps 2 backend. One of:
            1. `python3 ./src/quickapp/app.py`
            2. `docker build -t quickapp:latest -f Dockerfile . && docker run --rm -it quickapp:latest`
        3. Register the application in DIAL Core
            - Add the Quick App schema generated by `make dump_app_schema` to the Core configuration so Core knows the
              Quick App application schema. For Helm create/update a ConfigMap or mount the generated file under the
              path referenced by PREDEFINED_EXTRA_PATHS so Core can load it.
            - Ensure the chat UI has the Quick Apps feature enabled. Verify the chat service (or your ai-dial-chat
              deployment) includes `quick-apps` in its ENABLED_FEATURES flags so the UI will surface Quick Apps.
    - Notes:
        - Quick Apps will act as a client of DIAL Core; it must be able to reach the DIAL Core API (DIAL_URL) and, if
          required, present credentials (DIAL_API_KEY).
        - Registering on the DIAL Core side can be done by adding the application JSON to Core configuration or via your
          Core management UI — ensure the application record points to the Quick Apps service as appropriate.

### Utils

1. Format the code:

    ```bash
    make format                                        # Format all source files + regenerate app schema
    make format FILES="src/quickapp/core/agent/orchestrator.py"  # Format specific files (skips schema dump)
    ```

2. Run linters:

    ```bash
    make lint                   # Run all linters (always checks all source files)
    ```

3. Run individual tools (accept `FILES="..."` to target specific files):

    ```bash
    make black                  # Run black formatter
    make isort                  # Run isort formatter
    make flake8                 # Run flake8 linter
    make mypy                   # Run type checking
    ```

4. Run tests:

    ```bash
    make test                          # Run all unit tests
    make test ARGS="-k test_name -x"   # Run specific tests / fail fast
    make test_cov                      # Run unit tests with coverage report
    ```

5. Run arbitrary Python scripts:

    ```bash
    make run_python SCRIPT=src/scripts/dump_app_schema.py
    ```

6. To automatically apply black and isort on commit, enable PreCommit:

   ```bash
   make install_pre_commit_hooks
   ```

   This command will set up the git hook scripts.

## E2E & Integration tests

Refer to [Testing Guide](./src/tests/integration_tests/README.md) for detailed instructions on setting up and running tests.

## More

For more information about DIAL and its components, visit the [DIAL documentation](https://dialx.ai/docs). Join the DIAL
community on [Discord](https://discord.gg/ukzj9U9tEe) for support and collaboration.
