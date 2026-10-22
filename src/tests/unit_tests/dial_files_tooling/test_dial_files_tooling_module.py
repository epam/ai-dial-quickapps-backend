from unittest.mock import MagicMock

from quickapp.config.dial_files import DialFilesConfig
from quickapp.dial_files_tooling.dial_files_tooling_module import DialFilesToolingModule


def _builder():
    b = MagicMock()
    b.build.return_value = MagicMock()
    return b


def _make_builders():
    return tuple(_builder() for _ in range(10))


class TestDialFilesToolingModule:
    def test_cfg_none_returns_empty(self):
        module = DialFilesToolingModule()
        app_config = MagicMock()
        app_config.features = None
        result = module._provide_dial_files_tools(app_config, *_make_builders(), [], MagicMock())
        assert result == []

    def test_enabled_all_returns_all_tools(self):
        module = DialFilesToolingModule()
        app_config = MagicMock()
        app_config.features.dial_files = DialFilesConfig(enabled_tools="all")
        result = module._provide_dial_files_tools(app_config, *_make_builders(), [], MagicMock())
        assert len(result) == 10

    def test_read_chars_is_gated_by_enabled_tools(self):
        module = DialFilesToolingModule()
        app_config = MagicMock()
        app_config.features.dial_files = DialFilesConfig(enabled_tools=["read_chars"])
        builders = _make_builders()
        result = module._provide_dial_files_tools(app_config, *builders, [], MagicMock())
        assert len(result) == 1
        # read_chars is builder[2] (list, read_lines, read_chars)
        builders[2].build.assert_called_once()
        assert builders[2].build.call_args.kwargs["name"] == "internal_file_read_chars"

    def test_enabled_subset_filters_tools(self):
        module = DialFilesToolingModule()
        app_config = MagicMock()
        app_config.features.dial_files = DialFilesConfig(enabled_tools=["read_lines"])
        builders = _make_builders()
        result = module._provide_dial_files_tools(app_config, *builders, [], MagicMock())
        assert len(result) == 1
        # read is builder[1] (after list)
        builders[1].build.assert_called_once()
        builders[0].build.assert_not_called()

    def test_find_is_gated_by_enabled_tools(self):
        module = DialFilesToolingModule()
        app_config = MagicMock()
        app_config.features.dial_files = DialFilesConfig(enabled_tools=["find"])
        builders = _make_builders()
        result = module._provide_dial_files_tools(app_config, *builders, [], MagicMock())
        assert len(result) == 1
        # find is builder[4] (list, read_lines, read_chars, search, find)
        builders[4].build.assert_called_once()

    def test_path_transformer_injected_into_tools(self):
        module = DialFilesToolingModule()
        app_config = MagicMock()
        app_config.features.dial_files = DialFilesConfig(enabled_tools=["write"])
        builders = _make_builders()
        global_transformer = MagicMock()
        path_transformer = MagicMock()
        module._provide_dial_files_tools(
            app_config, *builders, [global_transformer], path_transformer
        )
        # write is builder[5] (list, read_lines, read_chars, search, find, write); the
        # path transformer must run last (after the global transformers).
        transformers = builders[5].build.call_args.kwargs["argument_transformers"]
        assert transformers == [global_transformer, path_transformer]
