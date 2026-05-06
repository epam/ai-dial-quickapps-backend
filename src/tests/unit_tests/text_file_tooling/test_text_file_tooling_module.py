from unittest.mock import MagicMock

from quickapp.config.text_file_tools import TextFileToolsConfig
from quickapp.text_file_tooling.text_file_tooling_module import TextFileToolingModule


def _make_builders():
    def _builder():
        b = MagicMock()
        b.build.return_value = MagicMock()
        return b

    return _builder(), _builder(), _builder(), _builder(), _builder()


class TestTextFileToolingModule:
    def test_cfg_none_returns_empty_list(self):
        module = TextFileToolingModule()
        app_config = MagicMock()
        app_config.features = None
        read, search, write, edit, delete = _make_builders()
        result = module._provide_text_file_tools(app_config, read, search, write, edit, delete)
        assert result == []

    def test_enabled_all_returns_five_tools(self):
        module = TextFileToolingModule()
        app_config = MagicMock()
        app_config.features.text_file_tools = TextFileToolsConfig(enabled_tools="all")
        read, search, write, edit, delete = _make_builders()
        result = module._provide_text_file_tools(app_config, read, search, write, edit, delete)
        assert len(result) == 5

    def test_enabled_subset_filters_tools(self):
        module = TextFileToolingModule()
        app_config = MagicMock()
        app_config.features.text_file_tools = TextFileToolsConfig(
            enabled_tools=["internal_text_file_read_lines"]
        )
        read, search, write, edit, delete = _make_builders()
        result = module._provide_text_file_tools(app_config, read, search, write, edit, delete)
        assert len(result) == 1
        read.build.assert_called_once()
        search.build.assert_not_called()
        write.build.assert_not_called()
        edit.build.assert_not_called()
        delete.build.assert_not_called()
