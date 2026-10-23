import pytest
from pydantic import ValidationError

from quickapp.config.dial_files import (
    DialFilesConfig,
    ToolCallResultOffloadConfig,
    ToolCallResultOffloadSettings,
)
from quickapp.config.tool_result_limit import ToolResultLimitSettings


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
