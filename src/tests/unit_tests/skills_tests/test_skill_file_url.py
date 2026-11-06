import pytest

from quickapp.skills.skill_file_url import (
    build_skill_file_url,
    format_skill_reference,
    is_skill_reference,
    normalize_skill_file_path,
    parse_skill_reference,
    skill_root_of_file_url,
)


class TestReference:

    def test_is_skill_reference(self):
        assert is_skill_reference("skill://s/a.py")
        assert is_skill_reference("skill://s")
        assert not is_skill_reference("files/b/a.py")
        assert not is_skill_reference("file:url::skill://s/a.py")

    def test_format(self):
        assert (
            format_skill_reference("data-cleanup", "scripts/clean.py")
            == "skill://data-cleanup/scripts/clean.py"
        )

    def test_parse(self):
        assert parse_skill_reference("skill://data-cleanup/scripts/clean.py") == (
            "data-cleanup",
            "scripts/clean.py",
        )

    @pytest.mark.parametrize(
        "value",
        ["skill://data-cleanup", "skill://data-cleanup/", "skill:///x.py", "files/a.py", ""],
    )
    def test_parse_returns_none_for_malformed(self, value: str):
        assert parse_skill_reference(value) is None


class TestNormalize:

    def test_strips_own_reference_prefix_and_whitespace(self):
        assert normalize_skill_file_path(" skill://s/scripts/a.py ", "s") == "scripts/a.py"

    @pytest.mark.parametrize("value", ["./scripts/a.py", "/scripts/a.py", "scripts/a.py"])
    def test_strips_decorations(self, value: str):
        assert normalize_skill_file_path(value, "s") == "scripts/a.py"

    def test_keeps_foreign_reference(self):
        assert normalize_skill_file_path("skill://other/a.py", "s") == "skill://other/a.py"


class TestBuildFileUrl:

    def test_builds_url(self):
        assert (
            build_skill_file_url("skills/b/data-cleanup", "scripts/clean.py")
            == "skills/b/data-cleanup/files/scripts/clean.py"
        )

    def test_percent_encodes_but_keeps_separators(self):
        assert (
            build_skill_file_url("skills/b/data-cleanup", "scripts/my file's.py")
            == "skills/b/data-cleanup/files/scripts/my%20file%27s.py"
        )

    def test_encodes_non_ascii(self):
        assert build_skill_file_url("skills/b/s", "данные.py") == (
            "skills/b/s/files/%D0%B4%D0%B0%D0%BD%D0%BD%D1%8B%D0%B5.py"
        )

    def test_trailing_slash_on_skill_url_is_not_doubled(self):
        assert build_skill_file_url("skills/b/s/", "a.py") == "skills/b/s/files/a.py"


class TestSkillRootOfFileUrl:

    def test_root(self):
        assert (
            skill_root_of_file_url("skills/b/data-cleanup/files/scripts/clean.py")
            == "skills/b/data-cleanup"
        )

    def test_nested_root(self):
        assert skill_root_of_file_url("skills/b/team/data-cleanup/files/a.py") == (
            "skills/b/team/data-cleanup"
        )

    def test_file_path_containing_files_segment_uses_first_files_segment(self):
        assert skill_root_of_file_url("skills/b/s/files/scripts/files/a.py") == "skills/b/s"

    @pytest.mark.parametrize(
        "value",
        [
            "files/b/a.py",
            "skills/b/data-cleanup",
            "skills/b/data-cleanup/files/",
            "/skills/b/s/files/a.py",
            "https://dial.example.com/skills/b/s/files/a.py",
            "skills/b/s/files/../../o/files/x",
            "skills/b/s/files/%2e%2e/x",
            "skills/b/s/files/./x",
        ],
    )
    def test_not_a_skill_file_url(self, value: str):
        assert skill_root_of_file_url(value) is None
