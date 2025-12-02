PYTHON ?= python3.13
POETRY_VERSION ?= 2.1.1
VENV_DIR ?= .venv
POETRY ?= $(VENV_DIR)/bin/poetry
SRC_DIRS = src/quickapp src/scripts

-include .env
export

init_env:
	$(PYTHON) -m venv $(VENV_DIR)
	$(VENV_DIR)/bin/pip install poetry==$(POETRY_VERSION) --quiet
	git submodule init
	git submodule update --recursive

install: init_env
	$(POETRY) install

install_dev: init_env
	$(POETRY) install --with dev

install_all: init_env
	$(POETRY) install --with dev

clean:
	-$(POETRY) run python -m src.scripts.clean || true
	rm -rf $(VENV_DIR)

lint: install_dev
	$(POETRY) check --lock
	$(POETRY) run flake8 ${SRC_DIRS}
	$(POETRY) run black ${SRC_DIRS} --check
	$(POETRY) run isort ${SRC_DIRS} --check-only --diff
	$(POETRY) run autoflake ${SRC_DIRS} --check
	$(POETRY) run mypy --show-error-codes ${SRC_DIRS}

mypy: install_dev
	$(POETRY) run mypy --show-error-codes ${SRC_DIRS}

format: install_dev
	$(POETRY) run autoflake ${SRC_DIRS}
	$(POETRY) run black ${SRC_DIRS}
	$(POETRY) run isort ${SRC_DIRS}

install_pre_commit_hooks:
	pre-commit install

run_chat: install_dev
	$(POETRY) run python src/quickapp/app.py

test: install_dev
	$(POETRY) run pytest src/tests/ --junitxml=reports/tests-unit.xml -m "not integration and not e2e"

dump_app_schema: install_dev
	$(POETRY) run python src/scripts/dump_app_schema.py generated-app-schema.json
