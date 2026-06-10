import pytest
from pydantic import ValidationError

from quickapp.config.dial_files import (
    READ_ONLY_DIAL_FILES_TOOLS,
    DialFilesConfig,
    resolve_enabled_dial_files_tools,
)


class TestDialFilesConfig:
    def test_defaults(self):
        cfg = DialFilesConfig()
        assert cfg.enabled_tools == "all"
        assert cfg.agent_home_dir == ""

    def test_list_of_tools_accepted(self):
        cfg = DialFilesConfig(enabled_tools=["read_lines", "search"])
        assert cfg.enabled_tools == ["read_lines", "search"]

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


class TestResolveEnabledDialFilesTools:
    def test_all_preset(self):
        enabled = resolve_enabled_dial_files_tools("all")
        assert enabled == {
            "list",
            "read_lines",
            "search",
            "write",
            "edit",
            "delete",
            "copy",
            "move",
        }

    def test_read_only_preset(self):
        enabled = resolve_enabled_dial_files_tools("read_only")
        assert enabled == set(READ_ONLY_DIAL_FILES_TOOLS)

    def test_write_only_list_unions_read_only(self):
        enabled = resolve_enabled_dial_files_tools(["write", "edit"])
        assert READ_ONLY_DIAL_FILES_TOOLS <= enabled
        assert "write" in enabled
        assert "edit" in enabled
