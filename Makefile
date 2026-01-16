SRC_DIRS = src/quickapp src/scripts
VENV_DIR ?= .venv
PYTHON ?= python
POETRY ?= poetry

SHELL := /bin/bash

-include .env
export

init_venv:
# 	@echo "===== Before init_venv ====="
# 	which $(PYTHON)
# 	$(PYTHON) --version
# 	which $(POETRY)
# 	$(POETRY) --version
# 	$(POETRY) env list --full-path
# 	$(POETRY) env info

	$(PYTHON) -m venv $(VENV_DIR)

# 	@echo "===== After init_venv ====="
# 	which $(PYTHON)
# 	$(PYTHON) --version
# 	which $(POETRY)
# 	$(POETRY) --version
# 	$(POETRY) env info
# 	$(POETRY) env list --full-path
# 	ls -lah /home/runner/work/ai-dial-quickapps-backend/ai-dial-quickapps-backend/.venv/bin/
# 	/home/runner/work/ai-dial-quickapps-backend/ai-dial-quickapps-backend/.venv/bin/python --version

install: init_venv
	$(POETRY) install

install_dev: init_venv
	$(POETRY) install --with dev

install_all: init_venv
	$(POETRY) install --with dev

clean:
	-$(POETRY) run $(PYTHON) -m src.scripts.clean
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
	$(POETRY) run $(PYTHON) src/quickapp/app.py

test: install_dev
	$(POETRY) run pytest src/tests/ --junitxml=reports/tests-unit.xml -m "not integration and not e2e"

dump_app_schema: install_dev
	$(POETRY) run $(PYTHON) src/scripts/dump_app_schema.py generated-app-schema.json

generate_dial_config: install_dev
	$(POETRY) run $(PYTHON) src/scripts/generate_dial_config.py --models \
	--template docker_compose_files/core/configuration/models-template.json \
	--config docker_compose_files/core/configuration/generated/models.json \
	--applications dial-rag,dial-web-rag \
    --schemas docker_compose_files/core/configuration/generated/application-schemas.json
