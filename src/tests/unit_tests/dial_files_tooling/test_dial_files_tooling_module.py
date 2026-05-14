from unittest.mock import MagicMock

from quickapp.config.dial_files import DialFilesConfig
from quickapp.dial_files_tooling.dial_files_tooling_module import DialFilesToolingModule


def _builder():
    b = MagicMock()
    b.build.return_value = MagicMock()
    return b


def _make_builders():
    return (
        _builder(),
        _builder(),
        _builder(),
        _builder(),
        _builder(),
        _builder(),
        _builder(),
        _builder(),
    )


class TestDialFilesToolingModule:
    def test_cfg_none_returns_empty(self):
        module = DialFilesToolingModule()
        app_config = MagicMock()
        app_config.features = None
        result = module._provide_dial_files_tools(app_config, *_make_builders())
        assert result == []

    def test_enabled_all_returns_eight_tools(self):
        module = DialFilesToolingModule()
        app_config = MagicMock()
        app_config.features.dial_files = DialFilesConfig(enabled_tools="all")
        result = module._provide_dial_files_tools(app_config, *_make_builders())
        assert len(result) == 8

    def test_enabled_subset_filters_tools(self):
        module = DialFilesToolingModule()
        app_config = MagicMock()
        app_config.features.dial_files = DialFilesConfig(enabled_tools=["read_lines"])
        builders = _make_builders()
        result = module._provide_dial_files_tools(app_config, *builders)
        assert len(result) == 1
        # read is builder[1] (after list)
        builders[1].build.assert_called_once()
        builders[0].build.assert_not_called()
