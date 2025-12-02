POETRY_PYTHON ?= python
SRC_DIRS = src/quickapp src/scripts

-include .env
export

init_venv:
	poetry env use ${POETRY_PYTHON}
	git submodule init
	git submodule update --recursive

install: init_venv
	poetry install

install_dev: init_venv
	poetry install --with dev

install_all: init_venv
	poetry install --with dev

clean: init_venv
	poetry run python -m src.scripts.clean
	poetry env remove --all

lint: install_dev
	poetry check --lock
	flake8 ${SRC_DIRS}
	black ${SRC_DIRS} --check
	isort ${SRC_DIRS} --check-only --diff
	autoflake ${SRC_DIRS} --check
	mypy --show-error-codes ${SRC_DIRS}

mypy:
	mypy --show-error-codes ${SRC_DIRS}

format:
	autoflake ${SRC_DIRS}
	black ${SRC_DIRS}
	isort ${SRC_DIRS}

install_pre_commit_hooks:
	pre-commit install

run_chat:
	poetry run python src/quickapp/app.py

test: install_dev
	poetry run pytest src/tests/ --junitxml=reports/tests-unit.xml -m "not integration and not e2e"

dump_app_schema: install_dev
	poetry run python src/scripts/dump_app_schema.py generated-app-schema.json
