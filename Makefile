SRC_DIRS = src/quickapp src/scripts src/tests
MYPY_DIRS = src/quickapp src/scripts
FILES ?= $(SRC_DIRS)
POETRY ?= poetry
PYTHON ?= python3

-include .env
export

# AI DIAL SDK: pydantic v2 mode
export PYDANTIC_V2=True

.PHONY: init_venv install install_dev install_integration install_all clean \
	lint mypy format install_pre_commit_hooks run_chat test test_cov \
	dump_app_schema generate_dial_config start_test_server stop_test_server \
	integration_test integration_test_run e2e_test run_python \
	black black_check isort isort_check autoflake autoflake_check flake8

init_venv:
	$(POETRY) env use $(PYTHON)

install: init_venv
	$(POETRY) install

install_dev: init_venv
	$(POETRY) install --with dev

install_integration: init_venv
	$(POETRY) install --with integration

install_all: init_venv
	$(POETRY) install --with dev,integration

clean:
	-$(POETRY) run python -m src.scripts.clean
	-$(POETRY) env remove --all

# --- Linting ---

lint: install_dev
	$(POETRY) check --lock
	$(POETRY) run flake8 $(SRC_DIRS)
	$(POETRY) run black $(SRC_DIRS) --check
	$(POETRY) run isort $(SRC_DIRS) --check-only --diff
	$(POETRY) run autoflake $(SRC_DIRS) --check
	$(POETRY) run mypy --show-error-codes $(MYPY_DIRS)
	$(POETRY) run python src/scripts/dump_app_schema.py docs/generated-app-schema.json --check

mypy: install_dev
	$(POETRY) run mypy --show-error-codes $(MYPY_DIRS)

# --- Formatting ---

format: install_dev
	$(POETRY) run autoflake $(FILES)
	$(POETRY) run black $(FILES)
	$(POETRY) run isort $(FILES)
ifeq ($(FILES), $(SRC_DIRS))
	$(POETRY) run python src/scripts/dump_app_schema.py docs/generated-app-schema.json
endif

# --- Individual tool targets (honor FILES variable) ---

black: install_dev
	$(POETRY) run black $(FILES)

black_check: install_dev
	$(POETRY) run black $(FILES) --check

isort: install_dev
	$(POETRY) run isort $(FILES)

isort_check: install_dev
	$(POETRY) run isort $(FILES) --check-only --diff

autoflake: install_dev
	$(POETRY) run autoflake $(FILES)

autoflake_check: install_dev
	$(POETRY) run autoflake $(FILES) --check

flake8: install_dev
	$(POETRY) run flake8 $(FILES)

# --- Running ---

install_pre_commit_hooks:
	pre-commit install

run_chat: install_dev
	$(POETRY) run python src/quickapp/app.py

run_python: install_dev
	$(if $(SCRIPT),,$(error SCRIPT is required, e.g. make run_python SCRIPT=path/to/script.py))
	$(POETRY) run python $(SCRIPT)

# --- Testing ---

PYTEST_UNIT = $(POETRY) run pytest src/tests/unit_tests -m "not integration and not e2e"

test: install_dev
	$(PYTEST_UNIT) --junitxml=reports/tests-unit.xml $(ARGS)

test_cov: install_dev
	$(PYTEST_UNIT) --cov=src/quickapp --cov-report=term-missing $(ARGS)

dump_app_schema: install_dev
	$(POETRY) run python src/scripts/dump_app_schema.py docs/generated-app-schema.json

generate_dial_config: install_dev
	$(POETRY) run python src/scripts/generate_dial_config.py --models \
	--template docker_compose_files/core/configuration/models-template.json \
	--config docker_compose_files/core/configuration/generated/models.json \
	--applications dial-rag,dial-web-rag

start_test_server:
	echo "Starting MCP + REST servers..."
	$(POETRY) run python src/tests/integration_tests/data_server_for_tests.py & echo $$! > .mcp_rest_server.pid
	sleep 1
	echo "Servers started with PID `cat .mcp_rest_server.pid`"

stop_test_server:
	@if [ -f .mcp_rest_server.pid ]; then \
		pid=$$(cat .mcp_rest_server.pid); \
		if kill -0 $$pid >/dev/null 2>&1; then \
			echo "Stopping MCP + REST servers..."; \
			kill $$pid; \
			rm -f .mcp_rest_server.pid; \
			echo "Servers stopped"; \
		else \
			echo "No running process found with PID $$pid"; \
			rm -f .mcp_rest_server.pid; \
		fi \
	else \
		echo "PID file not found. Are servers running?"; \
	fi

integration_test: install_integration
	$(MAKE) start_test_server
	$(POETRY) run pytest -n $(or ${WORKERS},logical) src/tests/integration_tests --model=${MODEL} --junitxml=reports/tests-integration-${MODEL_SHORT_NAME}.xml -m "integration" $(ARGS)
	$(MAKE) stop_test_server

integration_test_run:
	$(POETRY) run pytest --model=${MODEL} -m "integration" $(ARGS)

e2e_test: install_integration
	$(POETRY) run pytest -n $(or ${WORKERS},logical) --no-cache --junitxml=reports/tests-e2e.xml -m "e2e" $(ARGS)
