# Local Development

How to set up, run, and test Quick Apps locally.

Navigation: [Documentation hub](./README.md) · [Configuration / env vars](../CONFIGURATION.md) · [Root README](../README.md)


## Pre-requisites

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

## Setup

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
   full information about ENV variables can be found in [Configuration](../CONFIGURATION.md).

     ```bash
     cp .env.template .env
     ```

5. Generate DIAL configuration files:

    ```bash
    make generate_dial_config
    ```

   This command will generate two files in `docker_compose_files/core/configuration/generated/`:
    - `models.json` - contains the models configuration for DIAL.

6. Generate the local Keycloak TLS certificate (only needed for the docker-compose stack in
   [Option A](#run)):

    ```bash
    make generate_certs
    ```

   The local stack serves Keycloak over HTTPS at `https://keycloak.localtest.me:8443`. The
   certificates it signs are gitignored, so run this once before your first `docker compose up` —
   Docker creates a *directory* wherever a bind-mount source is missing, so without them Keycloak
   fails to start with a confusing error. The target is a no-op when the certificates already
   exist; pass `FORCE=1` to mint a new CA, which you then have to trust again.

   Then trust the generated CA so your browser accepts the login redirect (macOS):

    ```bash
    sudo security add-trusted-cert -d -r trustRoot \
      -k /Library/Keychains/System.keychain docker_compose_files/keycloak/certs/ca.crt
    ```

## Run

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

    - What the stack exposes:

      | URL                                     | What it is                                                              |
      |-----------------------------------------|-------------------------------------------------------------------------|
      | http://localhost:3010                   | DIAL Chat (legacy 0.x), which ships the Quick Apps 2.0 editor built in   |
      | http://localhost:3012                   | DIAL Chat (current), which embeds the editor below as an iframe          |
      | http://localhost:4600                   | Quick Apps 2.0 settings editor ([ai-dial-quickapps-frontend](https://github.com/epam/ai-dial-quickapps-frontend)) |
      | http://localhost:8090                   | DIAL Core                                                               |
      | https://keycloak.localtest.me:8443      | Keycloak (dev users: `admin-dev`/`admin-dev`, `user-dev`/`user-dev`)     |

    - Notes on authoring a Quick App through the UI:
        - Set `DEFAULT_ORCHESTRATOR_DEPLOYMENT_ID` in your `.env` to a tool-calling deployment. It is
          what puts a `default` on `orchestrator.deployment` in the generated schema; without it the
          editor cannot pre-fill that required field and creating an application fails with
          `400 Custom application validation failed`.
        - The chat at :3012 finds the editor through `DEV_QUICKAPPS_EDITOR_URL`, and is allowed to
          frame it by `ALLOWED_IFRAME_ORIGINS` — both already set on the `chat-new` service. The
          editor in turn only accepts being framed by the origin in its own
          `ALLOWED_FRAME_ANCESTORS`, so both sides must name each other.

    - Optional — DIAL Admin (UI + backend API, embedded H2 database):

      ```bash
      docker compose --profile admin up -d
      ```

      Or uncomment `COMPOSE_PROFILES=admin` in `.env` and run `docker compose up -d` as usual.

      Startup order: `admin-export-init` → `redis` / `core` (healthy) / `keycloak` → `admin-backend` (healthy) → `admin-frontend`.

      - Admin UI: http://localhost:3020 — sign in with Keycloak as `admin-dev`/`admin-dev`. The `admin`
        realm role is what grants DIAL Core admin access, so a `user-dev` login will not do.
      - Admin API: http://localhost:8092
      - Backend uses H2 with dev encryption keys; Core access via `dial_api_key`. Not production-equivalent.
      - **Admin → Core sync:** `admin-export-init` creates `docker_compose_files/core/admin-export/out.json` (gitignored) before Core starts. Admin exports merged config there (~15s after changes) and calls Core reload (`ENABLE_CONFIG_RELOAD`). Core loads static JSON from `docker_compose_files/core/configuration/` plus `out.json` (last), so Admin UI edits override the static files. Allow ~20s after a save for export + reload.
      - Populate Admin H2 initially via the Admin UI import flow, or keep an existing `admin-backend-data` volume. Core static config is not auto-imported into Admin on startup.

    - Notes:
        - If you want to run Quick Apps in Docker instead of on the host, update
          [application-schemas.json](../docker_compose_files/core/configuration/application-schemas.json) and change the Quick
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

## Utils

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

Refer to [Testing Guide](../src/tests/integration_tests/README.md) for detailed instructions on setting up and running tests.
