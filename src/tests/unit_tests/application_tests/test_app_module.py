from unittest.mock import MagicMock

from quickapp.application.app_module import AppModule
from quickapp.config.application import ApplicationConfig, Features, StageDisplayConfig, StageDisplayLevel


def _make_config(level: StageDisplayLevel | None = None) -> ApplicationConfig:
    mock = MagicMock(spec=ApplicationConfig)
    mock.features = Features(
        stage_display=StageDisplayConfig(level=level) if level is not None else StageDisplayConfig()
    )
    return mock


def _make_config_no_features() -> ApplicationConfig:
    mock = MagicMock(spec=ApplicationConfig)
    mock.features = None
    return mock


class TestProvideStageDisplayLevel:
    def _call(self, app_config: ApplicationConfig) -> StageDisplayLevel:
        module = AppModule()
        return module._AppModule__provide_stage_display_level(app_config)  # type: ignore[attr-defined]

    def test_default_config_returns_info(self):
        result = self._call(_make_config())
        assert result == StageDisplayLevel.INFO

    def test_error_level_from_config(self):
        result = self._call(_make_config(level=StageDisplayLevel.ERROR))
        assert result == StageDisplayLevel.ERROR

    def test_debug_level_from_config(self):
        result = self._call(_make_config(level=StageDisplayLevel.DEBUG))
        assert result == StageDisplayLevel.DEBUG

    def test_features_none_falls_back_to_info(self):
        result = self._call(_make_config_no_features())
        assert result == StageDisplayLevel.INFO
