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

### Environment Variables

| Variable                                   | Default                    | Required | Description                                                                                                  |
|--------------------------------------------|----------------------------|----------|--------------------------------------------------------------------------------------------------------------|
| **DIAL Core**                              |                            |          |                                                                                                              |
| `DIAL_URL`                                 | —                          | Yes      | URL of the DIAL Core API                                                                                     |
| `DIAL_API_VERSION`                         | `2025-01-01-preview`       | No       | API version for DIAL Core API                                                                                |
| **Logging**                                |                            |          |                                                                                                              |
| `LOG_FORMAT`                               | See below ¹                | No       | Custom logging format string. The default references `%(otel_context)s`, a synthetic field populated by `OtelAwareFormatter` to a `[trace_id=… span_id=… resource.service.name=… trace_sampled=…] ` block when OTEL log correlation is active (`OTEL_PYTHON_LOG_CORRELATION=true` and a span is in scope) and to an empty string otherwise. Custom formats may reference `%(otelTraceID)s`/`%(otelSpanID)s`/`%(otelServiceName)s`/`%(otelTraceSampled)s` directly, but those placeholders only resolve while correlation is on. |
| `LOG_DATE_FORMAT`                          | `%Y-%m-%d %H:%M:%S`        | No       | `strftime`-style format for the `%(asctime)s` field                                                          |
| `LOG_LEVEL`                                | `INFO`                     | No       | Root logger level (all loggers except quickapp)                                                              |
| `QUICKAPP_LOG_LEVEL`                       | `INFO`                     | No       | Log level for quickapp loggers                                                                               |
| `LOG_MULTILINE_LOG_ENABLED`                | `false`                    | No       | Enable multiline log mode                                                                                    |
| **Agent**                                  |                            |          |                                                                                                              |
| `DEFAULT_AGENT_MAX_ITERATIONS`             | `15`                       | No       | Maximum number of orchestrator iterations (`-1` for infinite)                                                |
| `CHAT_MESSAGE_LOG_LEN`                     | `-1` (unlimited)           | No       | Character limit for message content previews in logs                                                         |
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
| **Feature Gating**                         |                            |          |                                                                                                              |
| `ENABLE_PREVIEW_FEATURES`                  | `false`                    | No       | Enable preview features across the deployment (schema visibility + runtime activation)                       |
| **Templates**                              |                            |          |                                                                                                              |
| `PREDEFINED_EXTRA_PATHS`                   | —                          | No       | JSON list of directories layered on top of built-in predefined content (later entries override earlier ones) |
| `CONFIG_PROMPT_MAPPING`                    | *(built-in mapping)*       | No       | JSON mapping of predefined system prompts to DIAL Core deployments                                           |
| **Observability**                          |                            |          |                                                                                                              |
| `OTEL_SERVICE_NAME`                        | `quickapps`                | No       | Service name for OpenTelemetry tracing and metrics                                                           |
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

¹**Notes:**

- Variables listed above are a superset used across development and deployment modes. Some variables (e.g.
  `REMOTE_DIAL_*`) are only used when running the full local stack via docker-compose or during testing.
- For a standalone Quick Apps deployment the essential variable is only `DIAL_URL`
- For PyInterpreter tool setup
  see: [DIAL Core](https://github.com/epam/ai-dial-core), [PyInterpreter](https://github.com/epam/ai-dial-code-interpreter).

### Deprecated: Agent Instructions

> [!WARNING]
> The `config/predefined/instructions/` directory convention (formerly documented as "Agent instructions") has been
> removed. Instructions are replaced by [Agent Skills](docs/skills.md), which offer richer
> metadata,
> on-demand retrieval, and layered overrides. See the
> [migration guide](docs/skills.md#migrating-from-agent-instructions) for details.

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
    make format FILES="src/quickapp/agent/orchestrator.py"  # Format specific files (skips schema dump)
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
