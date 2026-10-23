from quickapp.common.tool_names import INTERNAL_FILE_READ_CHARS_TOOL_NAME
from quickapp.dial_files_tooling._utils import (
    MAX_LINE_CHARS,
    MAX_OUTPUT_CHARS,
    cap_output,
    truncate_line,
)


class TestTruncateLine:
    def test_short_line_unchanged(self):
        assert truncate_line("abc") == "abc"

    def test_line_at_limit_unchanged(self):
        line = "x" * MAX_LINE_CHARS
        assert truncate_line(line) == line

    def test_long_line_is_cut_with_marker_pointing_to_read_chars(self):
        line = "x" * (MAX_LINE_CHARS + 123)
        result = truncate_line(line)
        assert result.startswith("x" * MAX_LINE_CHARS)
        assert "123 more characters" in result
        assert INTERNAL_FILE_READ_CHARS_TOOL_NAME in result
        assert len(result) < MAX_LINE_CHARS + 300


class TestCapOutput:
    def test_short_text_unchanged(self):
        assert cap_output("a\nb") == ("a\nb", False)

    def test_text_at_limit_unchanged(self):
        text = "x" * MAX_OUTPUT_CHARS
        assert cap_output(text) == (text, False)

    def test_cuts_on_last_line_boundary_within_limit(self):
        line = "y" * 1000
        text = "\n".join([line] * 20)
        capped, truncated = cap_output(text)
        assert truncated is True
        assert len(capped) <= MAX_OUTPUT_CHARS
        assert capped == "\n".join([line] * capped.count("\n") + [line])

    def test_custom_limit_is_honoured(self):
        capped, truncated = cap_output("ab\ncd\nef", limit=5)
        assert (capped, truncated) == ("ab\ncd", True)

    def test_hard_cut_when_no_line_boundary_fits(self):
        text = "z" * (MAX_OUTPUT_CHARS * 2)
        capped, truncated = cap_output(text)
        assert truncated is True
        assert capped == "z" * MAX_OUTPUT_CHARS
