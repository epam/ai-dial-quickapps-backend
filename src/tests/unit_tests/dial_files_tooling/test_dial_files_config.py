import pytest
from pydantic import ValidationError

from quickapp.config.application import ApplicationConfig, Features
from quickapp.config.dial_files import (
    DialFilesConfig,
    ToolCallResultOffloadConfig,
    ToolCallResultOffloadSettings,
)
from quickapp.config.tool_result_limit import ToolResultLimitSettings
from tests.unit_tests.common.common import create_app_configuration


class TestExpandedTools:
    def test_all_is_every_tool(self):
        assert DialFilesConfig(enabled_tools="all").expanded_tools == {
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
        }

    def test_read_only_excludes_mutating_tools(self):
        assert DialFilesConfig(enabled_tools="read_only").expanded_tools == {
            "list",
            "read_lines",
            "read_chars",
            "search",
            "find",
        }

    def test_explicit_list_is_passed_through(self):
        cfg = DialFilesConfig(enabled_tools=["write", "read_lines"])
        assert cfg.expanded_tools == {"write", "read_lines"}


class TestDialFilesConfig:
    def test_defaults(self):
        cfg = DialFilesConfig()
        assert cfg.enabled_tools == "all"
        assert cfg.agent_home_dir == ""
        assert cfg.max_files_scanned == 50

    def test_max_files_scanned_must_be_positive(self):
        with pytest.raises(ValidationError):
            DialFilesConfig(max_files_scanned=0)

    def test_list_of_tools_accepted(self):
        cfg = DialFilesConfig(enabled_tools=["read_lines", "search"])
        assert cfg.enabled_tools == ["read_lines", "search"]

    def test_read_chars_tool_name_accepted(self):
        cfg = DialFilesConfig(enabled_tools=["read_lines", "read_chars"])
        assert cfg.enabled_tools == ["read_lines", "read_chars"]

    @pytest.mark.parametrize("preset", ["all", "read_only"])
    def test_presets_accepted(self, preset):
        assert DialFilesConfig(enabled_tools=preset).enabled_tools == preset

    @pytest.mark.parametrize("preset", ["write_only", "none"])
    def test_unknown_preset_rejected(self, preset):
        with pytest.raises(ValidationError):
            DialFilesConfig(enabled_tools=preset)

    def test_rejects_absolute_files_url(self):
        with pytest.raises(ValidationError, match="absolute"):
            DialFilesConfig(agent_home_dir="files/bucket/")

    def test_rejects_leading_slash(self):
        with pytest.raises(ValidationError, match="not start with"):
            DialFilesConfig(agent_home_dir="/bucket/")

    def test_rejects_missing_trailing_slash(self):
        with pytest.raises(ValidationError, match="end with"):
            DialFilesConfig(agent_home_dir="workspace")

    def test_rejects_dotdot_segment(self):
        with pytest.raises(ValidationError, match=r"\.\."):
            DialFilesConfig(agent_home_dir="foo/../bar/")

    def test_accepts_relative_subdir(self):
        cfg = DialFilesConfig(agent_home_dir="workspace/")
        assert cfg.agent_home_dir == "workspace/"

    def test_accepts_nested_subdir(self):
        cfg = DialFilesConfig(agent_home_dir="a/b/c/")
        assert cfg.agent_home_dir == "a/b/c/"

    def test_rejects_empty_segment(self):
        with pytest.raises(ValidationError, match="empty"):
            DialFilesConfig(agent_home_dir="a//b/")


class TestFeaturesDialFilesDefault:
    @pytest.mark.parametrize("raw", [{}, {"dial_files": None}, {"dial_files": {}}])
    def test_absent_null_and_empty_resolve_to_default_config(self, raw):
        cfg = Features.model_validate(raw).dial_files
        assert isinstance(cfg, DialFilesConfig)
        assert cfg.enabled_tools == "all"

    def test_explicit_settings_are_preserved(self):
        cfg = Features.model_validate({"dial_files": {"enabled_tools": "read_only"}}).dial_files
        assert cfg is not None
        assert cfg.enabled_tools == "read_only"

    @pytest.mark.parametrize("dial_files", [None, {}])
    def test_preview_gate_applies_to_absent_and_null(self, monkeypatch, dial_files):
        monkeypatch.delenv("ENABLE_PREVIEW_FEATURES", raising=False)
        raw = create_app_configuration([]).model_dump(mode="json")
        raw["features"]["dial_files"] = dial_files
        cfg = ApplicationConfig.model_validate(raw).features.dial_files  # type: ignore[union-attr]
        assert cfg is not None
        assert cfg.tool_call_result_offload is None

    def test_offload_follows_env_default_when_preview_enabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        raw = create_app_configuration([]).model_dump(mode="json")
        raw["features"]["dial_files"] = None
        cfg = ApplicationConfig.model_validate(raw).features.dial_files  # type: ignore[union-attr]
        assert cfg is not None
        assert cfg.tool_call_result_offload is not None
        assert cfg.tool_call_result_offload.enabled is True


class TestResultLimitConsistency:
    def test_default_threshold_fits_default_limit(self):
        assert ToolCallResultOffloadSettings().size_threshold <= ToolResultLimitSettings().max_chars

    def test_env_threshold_above_limit_is_rejected(self, monkeypatch):
        monkeypatch.setenv("TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD", "90000")
        with pytest.raises(ValidationError, match="TOOL_CALL_RESULT_LIMIT__MAX_CHARS"):
            ToolCallResultOffloadSettings()

    def test_raising_both_env_values_is_accepted(self, monkeypatch):
        monkeypatch.setenv("TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD", "90000")
        monkeypatch.setenv("TOOL_CALL_RESULT_LIMIT__MAX_CHARS", "120000")
        assert ToolCallResultOffloadSettings().size_threshold == 90_000

    def test_max_chars_must_be_positive(self):
        with pytest.raises(ValidationError):
            ToolResultLimitSettings(max_chars=0)

    def test_per_app_threshold_above_limit_is_rejected(self):
        with pytest.raises(ValidationError, match="must not exceed"):
            ToolCallResultOffloadConfig(size_threshold=80_001)

    def test_per_app_threshold_at_limit_is_accepted(self):
        assert ToolCallResultOffloadConfig(size_threshold=80_000).size_threshold == 80_000

    def test_per_app_threshold_follows_a_raised_env_limit(self, monkeypatch):
        monkeypatch.setenv("TOOL_CALL_RESULT_LIMIT__MAX_CHARS", "200000")
        assert ToolCallResultOffloadConfig(size_threshold=150_000).size_threshold == 150_000
