from unittest.mock import MagicMock

from quickapp.config.application import Features, StageDisplayConfig, StageDisplayLevel
from quickapp.shared.config_resolvers import StageDisplayResolver
from quickapp.shared.config_resolvers.stage_display_settings import StageDisplaySettings


def _resolver(env: StageDisplayLevel | None, app: StageDisplayLevel) -> StageDisplayResolver:
    settings = MagicMock(spec=StageDisplaySettings)
    settings.stage_display_level = env
    app_config = MagicMock()
    app_config.features = Features(stage_display=StageDisplayConfig(level=app))
    return StageDisplayResolver(settings, app_config)


def test_app_config_used_when_env_unset():
    assert _resolver(env=None, app=StageDisplayLevel.ERROR).resolve() == StageDisplayLevel.ERROR


def test_app_config_info_when_env_unset():
    assert _resolver(env=None, app=StageDisplayLevel.INFO).resolve() == StageDisplayLevel.INFO


def test_env_debug_wins_over_app_info():
    assert (
        _resolver(env=StageDisplayLevel.DEBUG, app=StageDisplayLevel.INFO).resolve()
        == StageDisplayLevel.DEBUG
    )


def test_env_error_wins_over_app_debug():
    assert (
        _resolver(env=StageDisplayLevel.ERROR, app=StageDisplayLevel.DEBUG).resolve()
        == StageDisplayLevel.ERROR
    )


def test_features_none_falls_back_to_info():
    settings = MagicMock(spec=StageDisplaySettings)
    settings.stage_display_level = None
    app_config = MagicMock()
    app_config.features = None
    assert StageDisplayResolver(settings, app_config).resolve() == StageDisplayLevel.INFO


def test_settings_real_default_is_none(monkeypatch):
    monkeypatch.delenv("DEFAULT_STAGE_DISPLAY_LEVEL", raising=False)
    assert StageDisplaySettings().stage_display_level is None


def test_settings_reads_env_debug(monkeypatch):
    monkeypatch.setenv("DEFAULT_STAGE_DISPLAY_LEVEL", "debug")
    assert StageDisplaySettings().stage_display_level == StageDisplayLevel.DEBUG


def test_settings_reads_env_error(monkeypatch):
    monkeypatch.setenv("DEFAULT_STAGE_DISPLAY_LEVEL", "error")
    assert StageDisplaySettings().stage_display_level == StageDisplayLevel.ERROR


def test_settings_reads_env_uppercase(monkeypatch):
    monkeypatch.setenv("DEFAULT_STAGE_DISPLAY_LEVEL", "DEBUG")
    assert StageDisplaySettings().stage_display_level == StageDisplayLevel.DEBUG
