from quickapp.config.text_file_tools import TextFileToolsConfig


class TestTextFileToolsConfig:
    def test_default_enabled_tools_is_all(self):
        cfg = TextFileToolsConfig()
        assert cfg.enabled_tools == "all"

    def test_list_of_tools_accepted(self):
        cfg = TextFileToolsConfig(
            enabled_tools=["internal_text_file_read_lines", "internal_text_file_search"]
        )
        assert cfg.enabled_tools == ["internal_text_file_read_lines", "internal_text_file_search"]
