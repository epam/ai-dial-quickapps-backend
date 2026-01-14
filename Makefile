SRC_DIRS = src/quickapp src/scripts
POETRY ?= poetry
PYTHON ?= python3.13

-include .env
export

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

lint: install_dev
	$(POETRY) check --lock
	$(POETRY) run flake8 $(SRC_DIRS)
	$(POETRY) run black $(SRC_DIRS) --check
	$(POETRY) run isort $(SRC_DIRS) --check-only --diff
	$(POETRY) run autoflake $(SRC_DIRS) --check
	$(POETRY) run mypy --show-error-codes $(SRC_DIRS)

mypy: install_dev
	$(POETRY) run mypy --show-error-codes $(SRC_DIRS)

format: install_dev
	$(POETRY) run autoflake $(SRC_DIRS)
	$(POETRY) run black $(SRC_DIRS)
	$(POETRY) run isort $(SRC_DIRS)

install_pre_commit_hooks: poetry-boot
	pre-commit install

run_chat: install_dev
	$(POETRY) run python src/quickapp/app.py

test: install_dev
	$(POETRY) run pytest src/tests/unit_tests --junitxml=reports/tests-unit.xml -m "not integration and not e2e"

dump_app_schema: install_dev
	$(POETRY) run python src/scripts/dump_app_schema.py generated-app-schema.json

generate_dial_config: install_dev
	$(POETRY) run python src/scripts/generate_dial_config.py --models \
	--template docker_compose_files/core/configuration/models-template.json \
	--config docker_compose_files/core/configuration/generated/models.json \
	--applications dial-rag,dial-web-rag \
    --schemas docker_compose_files/core/configuration/generated/application-schemas.json

start_test_server:
	echo "Starting MCP + REST servers..."
	python src/tests/integration_tests/data_server_for_tests.py & echo $$! > .mcp_rest_server.pid
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
	$(POETRY) run pytest -n $(or ${WORKERS},logical) src/tests/integration_tests --model=${MODEL} --junitxml=reports/tests-integration-${MODEL_SHORT_NAME}.xml -m "integration"
	$(MAKE) stop_test_server

e2e_test: install_integration
	$(POETRY) run pytest -n $(or ${WORKERS},logical) --no-cache --junitxml=reports/tests-e2e.xml -m "e2e"

