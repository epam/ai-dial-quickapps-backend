from unittest.mock import MagicMock

from quickapp.common.exceptions import InitializationException, OffloadConfigurationException
from quickapp.dial_files_tooling.dial_files_tooling_module import DialFilesToolingModule


def _make_offload(
    enabled: bool = True,
    size_threshold: int = 40_000,
    excluded_tools: "set[str] | None" = None,
) -> MagicMock:
    offload = MagicMock()
    offload.enabled = enabled
    offload.size_threshold = size_threshold
    offload.excluded_tools = excluded_tools if excluded_tools is not None else set()
    return offload


def _make_app_config(
    offload: "MagicMock | str" = "default",
    enabled_tools: "str | list[str]" = "all",
    dial_files_present: bool = True,
) -> MagicMock:
    cfg = MagicMock()
    if not dial_files_present:
        cfg.features.dial_files = None
        return cfg
    dial_files = cfg.features.dial_files
    dial_files.enabled_tools = enabled_tools
    dial_files.tool_call_result_offload = _make_offload() if offload == "default" else offload
    return cfg


def _resolve(app_config):
    return DialFilesToolingModule()._provide_offload_config(app_config)


def _exceptions(app_config) -> list[InitializationException]:
    module = DialFilesToolingModule()
    resolved = module._provide_offload_config(app_config)
    return module._provide_initialization_exceptions(resolved)


class TestOffloadConfigResolution:
    def test_disabled_when_dial_files_absent(self):
        config = _resolve(_make_app_config(dial_files_present=False))
        assert config.enabled is False

    def test_disabled_when_enabled_false(self):
        config = _resolve(_make_app_config(offload=_make_offload(enabled=False)))
        assert config.enabled is False

    def test_enabled_when_flag_set_and_all_tools(self):
        config = _resolve(_make_app_config(enabled_tools="all"))
        assert config.enabled is True

    def test_enabled_when_read_back_tools_explicitly_listed(self):
        config = _resolve(_make_app_config(enabled_tools=["read_lines", "search", "write"]))
        assert config.enabled is True

    def test_size_threshold_passed_through(self):
        config = _resolve(_make_app_config(offload=_make_offload(size_threshold=10_000)))
        assert config.size_threshold == 10_000

    def test_excluded_tools_is_frozenset_with_mandatory_read_back_tools(self):
        config = _resolve(_make_app_config(offload=_make_offload(excluded_tools={"tool_a"})))
        assert isinstance(config.excluded_tools, frozenset)
        assert config.excluded_tools == frozenset(
            {
                "tool_a",
                "internal_file_read_lines",
                "internal_file_search",
                "internal_skills_read_skill",
            }
        )

    def test_read_back_tools_always_excluded_even_when_config_omits_them(self):
        config = _resolve(_make_app_config(offload=_make_offload(excluded_tools=set())))
        assert "internal_file_read_lines" in config.excluded_tools
        assert "internal_file_search" in config.excluded_tools
        assert "internal_skills_read_skill" in config.excluded_tools

    def test_disabled_when_read_back_tools_not_in_enabled_list(self):
        config = _resolve(_make_app_config(enabled_tools=["write", "edit"]))
        assert config.enabled is False

    def test_disabled_when_only_one_read_back_tool_exposed(self):
        config = _resolve(_make_app_config(enabled_tools=["read_lines"]))
        assert config.enabled is False


class TestOffloadInitializationExceptions:
    def test_no_exception_when_dial_files_absent(self):
        assert _exceptions(_make_app_config(dial_files_present=False)) == []

    def test_no_exception_when_enabled_false(self):
        assert _exceptions(_make_app_config(offload=_make_offload(enabled=False))) == []

    def test_no_exception_when_enabled_false_and_read_back_tools_missing(self):
        app_config = _make_app_config(offload=_make_offload(enabled=False), enabled_tools=["write"])
        assert _exceptions(app_config) == []

    def test_no_exception_when_read_back_available(self):
        assert _exceptions(_make_app_config(enabled_tools="all")) == []

    def test_no_exception_when_read_back_tools_explicitly_listed(self):
        app_config = _make_app_config(enabled_tools=["read_lines", "search", "write"])
        assert _exceptions(app_config) == []

    def test_exception_when_read_back_tools_missing(self):
        exceptions = _exceptions(_make_app_config(enabled_tools=["write"]))
        assert len(exceptions) == 1
        assert isinstance(exceptions[0], OffloadConfigurationException)
        assert exceptions[0].missing_tools == ["read_lines", "search"]

    def test_exception_lists_only_missing_tool(self):
        exceptions = _exceptions(_make_app_config(enabled_tools=["read_lines"]))
        assert len(exceptions) == 1
        exc = exceptions[0]
        assert isinstance(exc, OffloadConfigurationException)
        assert exc.missing_tools == ["search"]

    def test_exception_is_soft(self):
        exceptions = _exceptions(_make_app_config(enabled_tools=["write"]))
        assert exceptions[0].is_hard is False
