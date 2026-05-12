import pytest
from pydantic import ValidationError

from quickapp.config.dial_files import DialFilesConfig


class TestDialFilesConfig:
    def test_defaults(self):
        cfg = DialFilesConfig()
        assert cfg.enabled_tools == "all"
        assert cfg.agent_home_dir == "files/{appdata}/"

    def test_list_of_tools_accepted(self):
        cfg = DialFilesConfig(enabled_tools=["internal_file_read_lines", "internal_file_search"])
        assert cfg.enabled_tools == ["internal_file_read_lines", "internal_file_search"]

    def test_rejects_missing_files_prefix(self):
        with pytest.raises(ValidationError, match="files/"):
            DialFilesConfig(agent_home_dir="bucket/")

    def test_rejects_missing_trailing_slash(self):
        with pytest.raises(ValidationError, match="end with"):
            DialFilesConfig(agent_home_dir="files/foo")

    def test_rejects_dotdot_segment(self):
        with pytest.raises(ValidationError, match=r"\.\."):
            DialFilesConfig(agent_home_dir="files/foo/../bar/")

    def test_rejects_unknown_template_token(self):
        with pytest.raises(ValidationError, match="unknown template token"):
            DialFilesConfig(agent_home_dir="files/{user}/")

    def test_accepts_appdata_template(self):
        cfg = DialFilesConfig(agent_home_dir="files/{appdata}/workspace/")
        assert cfg.agent_home_dir == "files/{appdata}/workspace/"

    def test_accepts_static_path(self):
        cfg = DialFilesConfig(agent_home_dir="files/shared-bucket/admin/")
        assert cfg.agent_home_dir == "files/shared-bucket/admin/"
