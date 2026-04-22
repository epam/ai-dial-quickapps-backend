from unittest.mock import MagicMock

from quickapp.tool_call_result_offload._settings import (
    ResolvedConfig,
    ToolCallResultOffloadSettings,
)
from quickapp.tool_call_result_offload.tool_call_result_offload_module import (
    ToolCallResultOffloadModule,
)


def _make_settings(**overrides) -> ToolCallResultOffloadSettings:
    defaults = dict(enabled=True, size_threshold=40_000, excluded_tools={"read_file_lines"})
    defaults.update(overrides)
    return ToolCallResultOffloadSettings.model_construct(**defaults)


def _make_app_config(app_offload=None) -> MagicMock:
    cfg = MagicMock()
    cfg.tool_defaults.tool_call_result_offload = app_offload
    return cfg


def _resolve(settings: ToolCallResultOffloadSettings, app_config) -> ResolvedConfig:
    return ToolCallResultOffloadModule()._provide_offload_config(settings, app_config)


class TestOffloadConfigResolution:
    def test_no_app_config_uses_env_defaults(self):
        settings = _make_settings(enabled=True, size_threshold=50_000)
        config = _resolve(settings, _make_app_config(app_offload=None))
        assert config.enabled is True
        assert config.size_threshold == 50_000

    def test_app_enabled_false_overrides_env(self):
        settings = _make_settings(enabled=True)
        app_offload = MagicMock()
        app_offload.enabled = False
        app_offload.size_threshold = 40_000
        config = _resolve(settings, _make_app_config(app_offload=app_offload))
        assert config.enabled is False

    def test_app_size_threshold_overrides_env(self):
        settings = _make_settings(size_threshold=40_000)
        app_offload = MagicMock()
        app_offload.enabled = True
        app_offload.size_threshold = 10_000
        config = _resolve(settings, _make_app_config(app_offload=app_offload))
        assert config.size_threshold == 10_000

    def test_excluded_tools_always_from_env(self):
        settings = _make_settings(excluded_tools={"tool_a", "tool_b"})
        app_offload = MagicMock()
        app_offload.enabled = True
        app_offload.size_threshold = 40_000
        config = _resolve(settings, _make_app_config(app_offload=app_offload))
        assert config.excluded_tools == frozenset({"tool_a", "tool_b"})

    def test_excluded_tools_is_frozenset(self):
        settings = _make_settings(excluded_tools={"tool_a"})
        config = _resolve(settings, _make_app_config(app_offload=None))
        assert isinstance(config.excluded_tools, frozenset)
