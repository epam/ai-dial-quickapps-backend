POETRY_PYTHON ?= $(if $(pythonLocation),$(pythonLocation)/bin/python,python3)
SRC_DIRS = src/quickapp src/scripts

-include .env
export

remove_venv:
	poetry env remove --all || true
	$(POETRY_PYTHON) -m venv .venv

init_venv: remove_venv
	poetry env use .venv/bin/python
	git submodule init
	git submodule update --recursive

install: init_venv
	poetry install

install_dev: init_venv
	poetry install --with dev

install_all: init_venv
	poetry install --with dev

clean: install_dev
	poetry run python -m src.scripts.clean
	poetry env remove --all

lint: install_dev
	poetry check --lock
	poetry run flake8 ${SRC_DIRS}
	poetry run black ${SRC_DIRS} --check
	poetry run isort ${SRC_DIRS} --check-only --diff
	poetry run autoflake ${SRC_DIRS} --check
	poetry run mypy --show-error-codes ${SRC_DIRS}

mypy: install_dev
	poetry run mypy --show-error-codes ${SRC_DIRS}

format: install_dev
	poetry run autoflake ${SRC_DIRS}
	poetry run black ${SRC_DIRS}
	poetry run isort ${SRC_DIRS}

install_pre_commit_hooks:
	pre-commit install

run_chat: install
	poetry run python src/quickapp/app.py

test: install_dev
	poetry run pytest src/tests/ --junitxml=reports/tests-unit.xml -m "not integration and not e2e"

dump_app_schema: install_dev
	poetry run python src/scripts/dump_app_schema.py generated-app-schema.json
