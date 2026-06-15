import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._glob import _glob_to_regex


def _matches(pattern: str, path: str) -> bool:
    return _glob_to_regex(pattern).fullmatch(path) is not None


class TestGlobToRegex:
    @pytest.mark.parametrize("path", ["x", "a/x", "a/b/x"])
    def test_double_star_slash_matches_any_depth(self, path: str):
        assert _matches("**/x", path)

    def test_double_star_slash_does_not_match_partial_segment(self):
        # '**/x' must not match 'foox' — the trailing 'x' is a whole final segment.
        assert not _matches("**/x", "foox")

    def test_double_star_only_spans_segments_as_a_whole_segment(self):
        # `**` is recursive only as a full path segment (`/**/`); `foo**` is a
        # within-segment wildcard, like `foo*` — it does not cross '/'.
        assert _matches("foo**", "foobar")
        assert not _matches("foo**", "foo/x")

    def test_single_star_does_not_cross_slash(self):
        assert _matches("*.csv", "a.csv")
        assert not _matches("*.csv", "data/a.csv")

    def test_double_star_then_star_matches_nested(self):
        assert _matches("data/**/*.json", "data/a.json")
        assert _matches("data/**/*.json", "data/x/y/a.json")

    def test_question_mark_is_single_non_slash_char(self):
        assert _matches("a?c", "abc")
        assert not _matches("a?c", "ac")
        assert not _matches("a?c", "a/c")

    def test_literal_is_escaped(self):
        # The '.' is a literal dot, not a regex wildcard.
        assert _matches("file.txt", "file.txt")
        assert not _matches("file.txt", "fileXtxt")

    def test_case_sensitive(self):
        assert not _matches("File.txt", "file.txt")

    def test_empty_pattern_raises(self):
        with pytest.raises(InvalidToolCallParameterException) as exc:
            _glob_to_regex("")
        assert exc.value.parameter_name == "pattern"
