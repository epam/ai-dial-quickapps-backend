import pytest

from quickapp.skills._exceptions import SkillFileNotFound
from quickapp.skills._file_paths import normalize_skill_file_path
from quickapp.skills._skill import SkillFileEntry
from quickapp.skills._xml import generate_skill_files_xml


class TestNormalizeSkillFilePath:
    """Shape guardrails applied to a model-supplied path before any I/O."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("SKILL.md", "SKILL.md"),
            ("references/api.md", "references/api.md"),
            ("  references/api.md  ", "references/api.md"),
            ("./references/api.md", "references/api.md"),
            ("references//api.md", "references/api.md"),
        ],
    )
    def test_accepts_and_normalizes_relative_paths(self, raw: str, expected: str):
        assert normalize_skill_file_path(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "/etc/passwd",
            "../outside.md",
            "references/../../outside.md",
            "references\\api.md",
        ],
    )
    def test_rejects_escapes_and_absolute_paths(self, raw: str):
        with pytest.raises(SkillFileNotFound):
            normalize_skill_file_path(raw)

    def test_rejection_names_the_offending_path(self):
        with pytest.raises(SkillFileNotFound, match=r"\.\./secret\.md"):
            normalize_skill_file_path("../secret.md")


class TestInventoryPathsRoundTrip:
    """Whatever `<skill_files>` advertises must be usable verbatim as
    `read_skill(file_path=...)`."""

    @pytest.mark.parametrize(
        "path",
        ["references/user's-guide.md", "assets/a&b.csv", "refs/<draft>.md", 'refs/"q".md'],
    )
    def test_awkward_names_survive_the_listing(self, path: str):
        rendered = generate_skill_files_xml([SkillFileEntry(path=path)])
        listed = rendered.splitlines()[1]

        # XML-escaping these turned `user's-guide.md` into `user&apos;s-guide.md`,
        # a name no lookup could resolve.
        assert listed == path
        assert normalize_skill_file_path(listed) == path
