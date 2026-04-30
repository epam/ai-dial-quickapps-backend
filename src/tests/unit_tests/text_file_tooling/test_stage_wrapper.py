from unittest.mock import MagicMock

from quickapp.common.tool_call_result import ToolCallResult
from quickapp.config.tools.display.paramenter import FormattedParameterConfig
from quickapp.text_file_tooling._stage_wrapper import _FileStageWrapper


def _make_wrapper() -> _FileStageWrapper:
    return _FileStageWrapper(stage=MagicMock(), tool_config=None)


class TestFileStageWrapper:
    def test_get_formatted_parameters_unknown_key_uses_fallback(self):
        wrapper = _make_wrapper()
        result = wrapper._get_formatted_parameters({"file_url": "files/b/f.txt"})
        assert "> #### Request:\n\r" in result
        assert "***file_url:*** files/b/f.txt\n\r" in result

    def test_get_formatted_parameters_ignored_key_omitted(self):
        wrapper = _make_wrapper()
        wrapper._parameters_config_map = {"file_url": FormattedParameterConfig(ignore=True)}
        result = wrapper._get_formatted_parameters({"file_url": "files/b/f.txt"})
        assert "file_url" not in result

    def test_get_formatted_parameters_display_config_uses_custom_name(self):
        wrapper = _make_wrapper()
        wrapper._parameters_config_map = {"file_url": FormattedParameterConfig(name="File URL")}
        result = wrapper._get_formatted_parameters({"file_url": "files/b/f.txt"})
        assert "File URL" in result
        assert "***file_url:***" not in result

    def test_build_debug_info_from_exception(self):
        wrapper = _make_wrapper()
        exc = ValueError("something went wrong")
        result = wrapper._build_debug_info_from_exception(exc)
        assert result == "### Exception:\n\rsomething went wrong\n\r"

    def test_build_debug_info_from_result(self):
        wrapper = _make_wrapper()
        tool_result = ToolCallResult(
            content="File written: files/b/notes.md", content_type="text/plain"
        )
        result = wrapper._build_debug_info_from_result(tool_result)
        assert result == "### Result:\n\rFile written: files/b/notes.md\n\r"
