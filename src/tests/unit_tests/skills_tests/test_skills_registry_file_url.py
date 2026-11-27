from unittest.mock import MagicMock

import pytest

from quickapp.skills.dial_resource import _DialSkillsContext
from quickapp.skills.exceptions import SkillFileNotFoundError, SkillFilesNotSupportedError
from quickapp.skills.registry._skills_registry import SkillsRegistry
from quickapp.skills.skills_provider import SkillFileReader
from tests.unit_tests.common.common import make_resolved_skill

_FILES = ("scripts/clean.py", "scripts/my file's.py")


def _registry(*, with_reader: bool = True) -> SkillsRegistry:
    context = _DialSkillsContext()
    context.extend_resolved_skills(
        [
            make_resolved_skill(
                "skills/b/data-cleanup",
                "data-cleanup",
                files=_FILES,
                reader=MagicMock(spec=SkillFileReader) if with_reader else None,
            )
        ]
    )
    return SkillsRegistry(providers=[context])


class TestResolveFileUrl:

    def test_resolves_listed_file(self):
        url = _registry().resolve_file_url("data-cleanup", "scripts/clean.py")

        assert url == "skills/b/data-cleanup/files/scripts/clean.py"

    @pytest.mark.parametrize(
        "file_path",
        ["skill://data-cleanup/scripts/clean.py", "./scripts/clean.py", " /scripts/clean.py"],
    )
    def test_accepts_decorated_paths(self, file_path: str):
        url = _registry().resolve_file_url("data-cleanup", file_path)

        assert url == "skills/b/data-cleanup/files/scripts/clean.py"

    def test_encodes_special_characters(self):
        url = _registry().resolve_file_url("data-cleanup", "scripts/my file's.py")

        assert url == "skills/b/data-cleanup/files/scripts/my%20file%27s.py"

    @pytest.mark.parametrize(
        "file_path",
        ["scripts/missing.py", "../other/x.py", "scripts%2Fclean.py", "SKILL.md"],
    )
    def test_file_outside_inventory_lists_available_files(self, file_path: str):
        with pytest.raises(SkillFileNotFoundError, match="scripts/clean.py"):
            _registry().resolve_file_url("data-cleanup", file_path)

    def test_unknown_skill(self):
        with pytest.raises(FileNotFoundError, match="Skill not found"):
            _registry().resolve_file_url("nope", "scripts/clean.py")

    def test_skill_without_bundled_files(self):
        with pytest.raises(SkillFilesNotSupportedError, match="has no bundled files"):
            _registry(with_reader=False).resolve_file_url("data-cleanup", "scripts/clean.py")
