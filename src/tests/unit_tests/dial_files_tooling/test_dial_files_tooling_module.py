from unittest.mock import MagicMock

import pytest

from quickapp.config.dial_files import DialFilesConfig
from quickapp.dial_files_tooling.dial_files_tooling_module import DialFilesToolingModule


def _builder():
    b = MagicMock()
    b.build.return_value = MagicMock()
    return b


def _make_builders():
    return tuple(_builder() for _ in range(10))


_TOOL_NAMES = (
    "list",
    "read_lines",
    "read_chars",
    "search",
    "find",
    "write",
    "edit",
    "delete",
    "copy",
    "move",
)
_READ_ONLY = {"list", "read_lines", "read_chars", "search", "find"}


def _built_tool_names(dial_files: DialFilesConfig | None) -> set[str]:
    app_config = MagicMock()
    app_config.features.dial_files = dial_files
    builders = _make_builders()
    DialFilesToolingModule()._provide_dial_files_tools(app_config, *builders, [], MagicMock())
    return {name for name, b in zip(_TOOL_NAMES, builders) if b.build.called}


class TestDefaultToolResolution:
    def test_absent_block_exposes_read_only_tools(self):
        assert _built_tool_names(None) == _READ_ONLY

    def test_absent_features_exposes_read_only_tools(self):
        app_config = MagicMock()
        app_config.features = None
        result = DialFilesToolingModule()._provide_dial_files_tools(
            app_config, *_make_builders(), [], MagicMock()
        )
        assert len(result) == 5

    def test_empty_block_still_exposes_all_tools(self):
        assert _built_tool_names(DialFilesConfig()) == set(_TOOL_NAMES)

    def test_read_only_preset_exposes_read_only_tools(self):
        assert _built_tool_names(DialFilesConfig(enabled_tools="read_only")) == _READ_ONLY

    @pytest.mark.parametrize("disabled", ["none", []])
    def test_none_and_empty_list_disable_the_defaults(self, disabled):
        assert _built_tool_names(DialFilesConfig(enabled_tools=disabled)) == set()

    def test_explicit_list_can_include_mutating_tools(self):
        cfg = DialFilesConfig(enabled_tools=["read_lines", "write"])
        assert _built_tool_names(cfg) == {"read_lines", "write"}

    def test_dial_files_config_falls_back_to_read_only_default(self):
        app_config = MagicMock()
        app_config.features.dial_files = None
        cfg = DialFilesToolingModule()._provide_dial_files_config(app_config)
        assert cfg.enabled_tools == "read_only"
        assert cfg.agent_home_dir == ""

    def test_absent_block_keeps_offload_disabled(self):
        app_config = MagicMock()
        app_config.features.dial_files = None
        offload = DialFilesToolingModule()._provide_offload_config(app_config)
        assert offload.enabled is False


class TestDialFilesToolingModule:

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
