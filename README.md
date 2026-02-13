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

## Quick start (general)

- Local development and run instructions, utilities and tests remain in this repository. For detailed setup commands (
  venv, poetry, make targets) see the project docs and Makefile.
- To run Quick Apps as a standalone service you need to provide DIAL Core endpoint and relevant environment variables.

## Configuration

All configuration-specific details (configuration model, environment variables, orchestrator, contexts, tool_sets, tool
fallback, attachments, authorization types, parameter/display configurations and examples) were moved to a dedicated
file:

- [Configuration](./CONFIGURATION.md) — full configuration reference and examples.

### Environment Variables

| Variable                                   | Default                    | Required | Description                                                                                                                          |
|--------------------------------------------|----------------------------|----------|--------------------------------------------------------------------------------------------------------------------------------------|
| **DIAL Core**                              |                            |          |                                                                                                                                      |
| `DIAL_URL`                                 | —                          | Yes      | URL of the DIAL Core API                                                                                                             |
| `DIAL_API_VERSION`                         | `2025-01-01-preview`       | No       | API version for DIAL Core API                                                                                                        |
| **Logging**                                |                            |          |                                                                                                                                      |
| `LOG_FORMAT`                               | See below ¹                | No       | Custom logging format string                                                                                                         |
| `LOG_LEVEL`                                | `INFO`                     | No       | Root logger level (all loggers except quickapp)                                                                                      |
| `QUICKAPP_LOG_LEVEL`                       | `INFO`                     | No       | Log level for quickapp loggers                                                                                                       |
| `PLOTLY_IMAGE_CONVERSION_LOG_LEVEL`        | `WARN`                     | No       | Log level for kaleido/choreographer (plotly image conversion)                                                                        |
| `LOG_MULTILINE_LOG_ENABLED`                | `false`                    | No       | Enable multiline log mode                                                                                                            |
| **Agent**                                  |                            |          |                                                                                                                                      |
| `DEFAULT_AGENT_MAX_ITERATIONS`             | `15`                       | No       | Maximum number of orchestrator iterations (`-1` for infinite)                                                                        |
| `CHAT_MESSAGE_LOG_LEN`                     | `-1` (unlimited)           | No       | Character limit for message content previews in logs                                                                                 |
| `SHOW_USAGE_STATISTICS`                    | `false`                    | No       | Include usage statistics in chat completion stream                                                                                   |
| `SHOW_EXECUTION_TIME_STAGE`                | `false`                    | No       | Show execution time stage in the UI                                                                                                  |
| **Python Interpreter**                     |                            |          |                                                                                                                                      |
| `PY_INTERPRETER_LOCAL_RUN`                 | `false`                    | No       | Run PyInterpreter locally instead of via DIAL Core API                                                                               |
| `PY_INTERPRETER_URL`                       | *(falls back to DIAL_URL)* | No       | URL of the PyInterpreter service                                                                                                     |
| `PY_INTERPRETER_API_KEY`                   | —                          | No       | API key for local-run PyInterpreter                                                                                                  |
| `PY_INTERPRETER_DEFAULT_SESSION_ID`        | —                          | No       | Default session ID for the PyInterpreter                                                                                             |
| `PY_INTERPRETER_ADDITIONAL_HANDLING_MODEL` | `gpt-4o-mini-2024-07-18`   | No       | Model for additional handling in PyInterpreter                                                                                       |
| `PY_INTERPRETER_CLIENT_TIMEOUT`            | `60.0`                     | No       | Timeout (seconds) for PyInterpreter client requests                                                                                  |
| `PY_INTERPRETER_CLIENT_MAX_RETRIES`        | `3`                        | No       | Max retries for PyInterpreter client requests                                                                                        |
| **Content Downloader**                     |                            |          |                                                                                                                                      |
| `CONTENT_DOWNLOADER_FILE_SIZE_LIMIT`       | `20971520` (20 MB)         | No       | Max file size in bytes for the content downloader tool                                                                               |
| **Templates**                              |                            |          |                                                                                                                                      |
| `PREDEFINED_BASE_PATH`                     | `config/predefined`        | No       | Base path for predefined templates                                                                                                   |
| `CONFIG_PROMPT_MAPPING`                    | *(built-in mapping)*       | No       | JSON mapping of predefined system prompts to DIAL Core deployments                                                                   |
| **Observability**                          |                            |          |                                                                                                                                      |
| `OTEL_SERVICE_NAME`                        | `quickapps`                | No       | Service name for OpenTelemetry tracing and metrics                                                                                   |
| **Scripts & Tests**                        |                            |          |                                                                                                                                      |
| `REMOTE_DIAL_URL`                          | —                          | No       | URL of the remote DIAL Core, used only by `generate_dial_config` script and e2e/integration tests                                    |
| `REMOTE_DIAL_API_KEY`                      | —                          | No       | API key of the remote DIAL Core, used only by `generate_dial_config` script and e2e/integration tests                                |

¹ `LOG_FORMAT` default depends on `LOG_MODE`: when `LOG_MODE=dev` it is `%(message)s`, otherwise
`%(asctime)s [%(levelname)s] |%(process)d| %(pathname)s:%(lineno)d: %(message)s`.

**Notes:**

- Variables listed above are a superset used across development and deployment modes. Some variables (e.g.
  `REMOTE_DIAL_*`) are only used when running the full local stack via docker-compose or during testing.
- For a standalone Quick Apps deployment the essential variable is only `DIAL_URL`
- For PyInterpreter tool setup
  see: [DIAL Core](https://github.com/epam/ai-dial-core), [PyInterpreter](https://github.com/epam/ai-dial-code-interpreter).

### Agent instructions

You can define instructions for Quick Apps by adding one or more Markdown files to config/predefined/instructions. These
files are appended after the predefined system prompt (prompt first, instructions after) to form the final system
message the project uses.
How to add instructions

- Add *.md files to config/predefined/instructions.
- Name files to control order (for example 01-overview.md, 02-guidelines.md); files are concatenated in filename sort
  order.
- Use blank lines between sections inside files; when combined, files are separated by a blank line.
- Restart the service to apply changes.
  Notes
- If no files are present, no extra instructions will be added.
- Check application logs if expected instructions do not appear.

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
    - `application-schemas.json` - contains the QuickApps schema.

### Run

- Option A — Full local stack (docker-compose)
    - Use this if you want to bring up DIAL Core, chat UI, redis, themes and adapters locally for end-to-end development
      and testing.
    - This docker-compose setup launches multiple services and uses internal hostnames (for example core, redis,
      themes). Example:

      ```bash
      docker compose up -d
      ```

    - Notes:
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
            - PREDEFINED_BASE_PATH if you rely on predefined templates/toolsets.
        2. Run the Quick Apps 2 backend. One of:
            1. `python3 ./src/quickapp/app.py`
            2. `docker build -t quickapp:latest -f Dockerfile . && docker run --rm -it quickapp:latest`
        3. Register the application in DIAL Core
            - Add the Quick App schema generated by `make dump_app_schema` to the Core configuration so Core knows the
              Quick App application schema. For Helm create/update a ConfigMap or mount the generated file under the
              path referenced by PREDEFINED_BASE_PATH so Core can load it.
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
    make format
    ```

2. Run linters:

    ```bash
    make lint
    ```

3. To automatically apply black and isort on commit, enable PreCommit:

   ```bash
   make install_pre_commit_hooks
   ```

   This command will set up the git hook scripts.

## E2E & Integration tests:

    refer to [Testing Guide](./src/tests/integration_tests/README.md) for detailed instructions on setting up and running tests.

## Documentation

- [Configuration Reference](./CONFIGURATION.md) - Full configuration model, environment variables, and examples
- [Technical Documentation](./docs/README.md) - Internal architecture and design documents

## More

For more information about DIAL and its components, visit the [DIAL documentation](https://dialx.ai/docs). Join the DIAL
community on [Discord](https://discord.gg/ukzj9U9tEe) for support and collaboration.
