PYTHON ?= $(if $(pythonLocation),$(pythonLocation)/bin/python,python3)
POETRY := $(PYTHON) -m poetry
SRC_DIRS = src/quickapp src/scripts

-include .env
export

.PHONY: poetry-boot
poetry-boot:
	@$(PYTHON) -m pip install --upgrade --quiet "poetry==2.1.1"

init_venv: poetry-boot
	$(POETRY) env use $(PYTHON)
	git submodule init
	git submodule update --recursive

install: init_venv
	$(POETRY) install

install_dev: init_venv
	$(POETRY) install --with dev

install_all: init_venv
	$(POETRY) install --with dev

clean: poetry-boot
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
	$(POETRY) run pytest src/tests/ --junitxml=reports/tests-unit.xml -m "not integration and not e2e"

dump_app_schema: install_dev
	$(POETRY) run python src/scripts/dump_app_schema.py generated-app-schema.json
