# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Quick Apps 2.0** — DIAL's no-code agent builder. Users wire LLMs with tools (REST, MCP, DIAL deployments) via JSON-schema-validated manifests.

**Stack:**
- **Language**: Python 3.13 (strict version requirement)
- **Framework**: FastAPI + Pydantic v2 + injector (DI)
- **Build tool**: Poetry 2.x
- **Source**: `src/quickapp/` (app), `src/tests/` (tests), `src/scripts/` (utilities)

## Commands

| Task | Command | Notes |
|------|---------|-------|
| Install dev deps | `make install_dev` | |
| Install dev + integration deps | `make install_all` | |
| Run app (dev) | `make run_chat` | |
| Run a Python script | `make run_python SCRIPT=path/to/script.py` | |
| Format code | `make format` | Runs: `autoflake` → `black` → `isort` → schema dump (schema dump only when formatting all `SRC_DIRS`) |
| Format specific files/dirs | `make format FILES="src/quickapp/core/agent"` | |
| Lint (all checks) | `make lint` | Runs: `poetry check --lock` + `flake8` + `black --check` + `isort --check` + `autoflake --check` + `mypy` + schema check |
| Type check only | `make mypy` | |
| Unit tests | `make test` | |
| Unit tests (filtered) | `make test ARGS="-k test_name -x"` | |
| Unit tests + coverage | `make test_cov` | |
| Integration tests (single model) | `make integration_test MODEL=<model>` | Automatically starts/stops the local MCP + REST test server |
| Integration tests (all models, local) | `make integration_test_all` | Sequential run over `INTEGRATION_TEST_MODELS` in Makefile |
| Integration tests (CI) | `make integration_test_ci MODEL=<model>` | Used by the manual **Integration Tests** GitHub Actions workflow |
| E2E tests | `make e2e_test` | |
| Dump app schema | `make dump_app_schema` | |

> **Note:** `PYDANTIC_V2=True` is enforced by the Makefile (aidial-sdk requirement) — do not override it.

## Architecture

**QuickApps 2.0** is a DIAL application composer. It lets users declaratively wire LLMs with tools
(REST APIs, MCP servers, DIAL deployments) via JSON-schema-validated manifests.

Entry points: `src/quickapp/app.py` (process) and `src/quickapp/app_factory.py` (DI assembly).\
Each feature is an `injector.Module` wired into the `Injector` in `app_factory.py`.\
Cross-cutting shared code lives in `common/` (a flat utility bag). Two packages each expose a
`<pkg>_module: list[Module]` array that `app_factory` splices into the module list instead of
registering each entry separately: `core/` exposes `core_module` (the app's central modules —
`AppModule` + `AgentModule`), and `shared/` exposes `shared_module` (cross-cutting utility modules with
their own DI wiring; today `ExternalFetchModule` in `shared/external_fetch/`).

→ Deep dive: [`docs/agent.md`](docs/agent.md) | [`docs/skills.md`](docs/skills.md) | [`docs/file_transfer.md`](docs/file_transfer.md) | [`docs/error_handling.md`](docs/error_handling.md)

### Dependency Injection (Core Pattern)

**Everything flows through DI.** The `injector` library wires the app together:

- `app_factory.py` builds the root `Injector` with ~14 feature modules
- Each module (`*_module.py`) has a `configure(binder)` method that binds types to implementations
- Classes use `@inject` decorator and receive dependencies via `__init__`
- **Never** import and instantiate another module's services directly — always inject

### Request Lifecycle

Request → HTTP endpoint (`application/`) → Config resolution → Tool initialization → **Orchestrator loop** (`agent/orchestrator.py`) → LLM call → Tool execution → Repeat until done or max iterations → Streaming response

### Four Tool Types

1. **REST API** (`rest_api_tooling/`) — External HTTP APIs
2. **DIAL Deployment** (`dial_deployment_tooling/`) — DIAL-native model/app tools
3. **MCP** (`mcp_tooling/`) — Model Context Protocol servers
4. **Internal** (`internal_tooling/`) — Built-in Python tools (pandas, plotly, etc.)

### File Transfer (`file_transfer/`)

`FileLoaderService` (in `file_transfer/`), `ExternalUrlFetcher` (in `shared/external_fetch/`), and `DialFilePromoter`
(in `dial_core_services/`) together resolve any URL the agent encounters (DIAL or external) into bytes or a durable
DIAL file. External egress is gated by a two-tier policy: the admin `EXTERNAL_URL_FETCH_ENABLED` env switch and the
per-app `features.external_url_fetch.enabled` field. The deployment-attachment path is capability-aware via
`Deployment.features.url_attachments`. See [`docs/file_transfer.md`](docs/file_transfer.md).

### Skills

Skills are reusable instruction modules. Predefined skills are loaded at startup from `config/predefined/skills/`.
DIAL prompt skills (`dial_prompt_skills/`) are fetched at request time from DIAL Core's prompts API.
`SkillsRegistry` merges both sources per request.

### Configuration Model

JSON-schema validated manifests with four sections: orchestrator config (deployment, system prompt, max iterations), contexts (file attachments), tool sets, and skills (optional). Schema is auto-generated — run `make dump_app_schema` after changing config models.

### Preview Features

Preview-gated modules are skipped when `ENABLE_PREVIEW_FEATURES=false`.

> Key env vars: `ENABLE_PREVIEW_FEATURES` (default `false`), `DIAL_URL` (DIAL Core endpoint). Full reference: `CONFIGURATION.md`.

## Code Style

See `CODESTYLE.md` for full details. Key rules:

- **DI**: Constructor injection only — never instantiate services directly across module boundaries.
- **Types**: Always add type hints. Use modern generics: `list[str]`, `dict[str, int]`, `str | None`.
- **Data containers**: Use Pydantic `BaseModel` (not `@dataclass`) for value objects; use `model_config = ConfigDict(frozen=True)` when immutability is wanted.
- **Visibility**: `_` prefix for all internal attributes/methods.
- **Logging**: Use `logging` module; never `print()`.
- **Imports**: stdlib → third-party → local, explicit only (no `*` imports).

## Testing

Unit tests are fast and isolated. Integration tests use cached LLM responses for determinism.

→ Details auto-loaded via `.claude/rules/` when working in test directories.

## Adding Features

When adding a new feature: create a `*_module.py` with `configure(binder)`, register it in `app_factory.py`, and follow the DI pattern. Run `make dump_app_schema` if any config models changed.

## Code Navigation

**Always use the LSP tool first** for any code exploration task — finding what something is, tracing how it's used, or understanding code structure. This includes questions like "what is X?", "where is X defined?", or "who calls X?".

- `goToDefinition` / `goToTypeDefinition` — jump to where a symbol is defined
- `findReferences` — find all usages of a symbol
- `hover` — get type info and docstrings without opening files
- `documentSymbol` — overview of a file's structure

**Do not default to Grep or Read for code navigation.** Only fall back to Grep when you need a text-based search that LSP can't answer (e.g., searching comments, string literals, or patterns across non-code files).

## After Every Coding Task

1. `make format` — auto-format and regenerate schema
2. `make lint` — validate no regressions
3. Run `make test` only when explicitly requested
