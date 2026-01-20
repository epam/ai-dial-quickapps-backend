# Testing Guide

## 1. Prerequisites

### 1.1 Access to DIAL Core
- Have access to a running DIAL Core instance with the `pyinterpreter` module installed.
    - DIAL Core: https://github.com/epam/ai-dial-core
    - PyInterpreter docs: https://github.com/epam/ai-dial-code-interpreter

### Create the .env file to store environment variables for test runs
- Fill these environment variables with correct placeholder values:
    - `REMOTE_DIAL_URL=<URL of DIAL CORE>`
    - `REMOTE_DIAL_API_KEY=<Your API-KEY>`
    - `DIAL_URL=<URL of DIAL CORE>` 
    - `DIAL_API_KEY=<Your API-KEY>`

### PY Interpreter tests
- `PY_INTERPRETER_LOCAL_RUN=true`
- `PY_INTERPRETER_API_KEY=<Your API-KEY>`
- `PY_INTERPRETER_URL=<URL of DIAL CORE>`

### Additional logs if logs are not sufficient
- `QUICKAPP_LOG_LEVEL=DEBUG`

## 2. Model differences and required changes
- Different DIAL Core instances may expose different models. Adjust tests accordingly.

Changes required:
- `e2e` tests:
    - Edit `test_e2e.py` to add or remove tests that reference missing models.
- `integration` tests:
    - Set `REFRESH=TRUE` to build the cache of model responses during first run of integration tests.
    - Update the agent/orchestrator model list in `src/tests/test_runner/cache/cache_middleware.py` (the `AGENT_MODELS` list) to include or remove models available on your instance.

Notes:
- Building the cache (with `REFRESH=TRUE`) records real model responses for later deterministic integration runs.
- Keep the cached responses committed if you intend to share reproducible integration tests.


## 3. Execute tests
- Run end-to-end tests: `make e2e_test`
- Run end-to-end tests: `make e2e_test`

## Test types (brief)
- `e2e`:
    - Simple, "happy path" test(s) validating that all components integrate and function end-to-end.
- `integration`:
    - Multiple scenarios using cached model responses of actual tool calls; validates orchestrator behavior only.
    - May fail due to agent response entropy. When an integration test fails, review the failing test and cached model response individually.

## Troubleshooting
- If tests fail because of missing models:
    - Update `test_e2e.py` and `AGENT_MODELS` in `cache_middleware.py`.
- If integration tests fail nondeterministically:
    - Rebuild cache with `REFRESH=TRUE`, inspect stored responses, and decide if they should be refreshed/committed.