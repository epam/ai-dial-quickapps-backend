import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic_core import PydanticUndefined

from quickapp.agent.agent_settings import AgentSettings
from quickapp.config.application import _orchestrator_deployment_field
from quickapp.config.dial_deployment import DialDeploymentConfig

_ENV_VAR = "DEFAULT_ORCHESTRATOR_DEPLOYMENT_ID"
_SAMPLE_DEPLOYMENT = "gpt-4o-2024-05-13"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SRC_PATH = _REPO_ROOT / "src"


class TestAgentSettingsDefaultDeploymentId:
    def test_loads_via_alias(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, _SAMPLE_DEPLOYMENT)
        assert AgentSettings().default_orchestrator_deployment_id == _SAMPLE_DEPLOYMENT

    def test_unset_is_none(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert AgentSettings().default_orchestrator_deployment_id is None

    def test_blank_value_is_none(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, "   ")
        assert AgentSettings().default_orchestrator_deployment_id is None

    def test_value_is_stripped(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, "  gpt-4o  ")
        assert AgentSettings().default_orchestrator_deployment_id == "gpt-4o"


class TestOrchestratorDeploymentFieldHelper:
    def test_env_unset_returns_required_field(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        field = _orchestrator_deployment_field()
        assert field.default is PydanticUndefined
        assert field.default_factory is None
        assert field.json_schema_extra is None
        assert field.description == "The configuration for the orchestrator DIAL deployment."

    def test_env_set_returns_field_with_default(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, _SAMPLE_DEPLOYMENT)
        field = _orchestrator_deployment_field()
        assert field.default_factory is not None

        instance = field.default_factory()
        assert isinstance(instance, DialDeploymentConfig)
        assert instance.deployment_id == _SAMPLE_DEPLOYMENT

        assert field.json_schema_extra == {"default": {"deployment_id": _SAMPLE_DEPLOYMENT}}
        assert field.description == "The configuration for the orchestrator DIAL deployment."

    def test_default_factory_produces_fresh_instances(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, _SAMPLE_DEPLOYMENT)
        field = _orchestrator_deployment_field()
        first = field.default_factory()
        second = field.default_factory()
        assert first is not second


def _dump_schema_in_subprocess(env: dict[str, str]) -> dict:
    """Run a fresh Python interpreter to dump ApplicationConfig.model_json_schema().

    Module-level evaluation of OrchestratorConfig.deployment freezes the env-driven
    default at import time, so the only reliable way to assert "schema under env X"
    is a fresh process.
    """
    script = textwrap.dedent("""
        import json
        import sys

        sys.path.insert(0, sys.argv[1])

        from quickapp.config.application import ApplicationConfig

        json.dump(ApplicationConfig.model_json_schema(include_dial_fields=False), sys.stdout)
        """)
    proc = subprocess.run(
        [sys.executable, "-c", script, str(_SRC_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _baseline_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop(_ENV_VAR, None)
    return env


@pytest.fixture(scope="module")
def baseline_schema() -> dict:
    return _dump_schema_in_subprocess(_baseline_env())


@pytest.fixture(scope="module")
def with_default_schema() -> dict:
    env = _baseline_env()
    env[_ENV_VAR] = _SAMPLE_DEPLOYMENT
    return _dump_schema_in_subprocess(env)


class TestSchemaReflectsEnvDefault:
    def test_env_unset_deployment_is_required(self, baseline_schema):
        orchestrator = baseline_schema["properties"]["orchestrator"]
        deployment = orchestrator["properties"]["deployment"]
        assert "default" not in deployment
        assert "deployment" in orchestrator["required"]

    def test_env_set_injects_default_and_drops_required(self, with_default_schema):
        orchestrator = with_default_schema["properties"]["orchestrator"]
        deployment = orchestrator["properties"]["deployment"]
        assert deployment["default"] == {"deployment_id": _SAMPLE_DEPLOYMENT}
        assert "deployment" not in orchestrator.get("required", [])

    def test_env_set_does_not_mutate_dial_deployment_config_def(
        self, baseline_schema, with_default_schema
    ):
        # The shared $def must stay identical — only the referencing slot gains a default.
        assert (
            baseline_schema["$defs"]["DialDeploymentConfig"]
            == with_default_schema["$defs"]["DialDeploymentConfig"]
        )

    def test_env_blank_behaves_like_unset(self):
        env = _baseline_env()
        env[_ENV_VAR] = "   "
        schema = _dump_schema_in_subprocess(env)
        orchestrator = schema["properties"]["orchestrator"]
        assert "default" not in orchestrator["properties"]["deployment"]
        assert "deployment" in orchestrator["required"]
