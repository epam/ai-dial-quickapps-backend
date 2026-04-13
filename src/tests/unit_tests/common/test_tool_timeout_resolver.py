from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from quickapp.common.tool_timeout_resolver import ToolTimeoutResolver
from quickapp.common.tool_timeout_settings import ToolTimeoutSettings
from quickapp.config.application import ToolDefaults


def _resolver(env: float, app: float | None) -> ToolTimeoutResolver:
    settings = MagicMock(spec=ToolTimeoutSettings)
    settings.default_tool_timeout_seconds = env
    app_config = MagicMock()
    app_config.tool_defaults = ToolDefaults(timeout_seconds=app)
    return ToolTimeoutResolver(settings, app_config)


def test_env_default_used_when_app_unset():
    assert _resolver(env=300, app=None).resolve() == 300


def test_env_custom_used_when_app_unset():
    assert _resolver(env=600, app=None).resolve() == 600


def test_app_only():
    assert _resolver(env=300, app=900).resolve() == 900


def test_app_overrides_env():
    assert _resolver(env=600, app=900).resolve() == 900


def test_settings_real_default_is_300():
    # Sanity-check the chosen deployment-wide default.
    assert ToolTimeoutSettings().default_tool_timeout_seconds == 300.0


def test_tool_defaults_default_factory_materialises():
    td = ToolDefaults()
    assert td.timeout_seconds is None


@pytest.mark.parametrize("bad", [0, -1, -100, 3601, 10000])
def test_invalid_app_timeout_rejected(bad):
    with pytest.raises(ValidationError):
        ToolDefaults(timeout_seconds=bad)


def test_valid_bounds_accepted():
    ToolDefaults(timeout_seconds=0.1)
    ToolDefaults(timeout_seconds=3600)
    ToolDefaults(timeout_seconds=None)
