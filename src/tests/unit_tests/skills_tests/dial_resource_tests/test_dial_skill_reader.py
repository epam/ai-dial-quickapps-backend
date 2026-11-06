from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.skills.dial_resource._dial_skill_reader import DialSkillReader
from quickapp.skills.exceptions import SkillFileNotFoundError
from tests.unit_tests.common.common import make_resolved_skill


def _reader() -> tuple[DialSkillReader, MagicMock]:
    client = MagicMock()
    client.read_text_file = AsyncMock(return_value="body")
    return DialSkillReader(client), client


class TestReadBundledFile:

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "file_path",
        ["references/eu.md", "skill://refund-policy/references/eu.md", "./references/eu.md"],
    )
    async def test_accepts_listed_forms(self, file_path: str):
        reader, client = _reader()
        skill = make_resolved_skill(
            "skills/b/refund-policy", "refund-policy", files=("references/eu.md",)
        )

        assert await reader.read_bundled_file(skill, file_path) == "body"
        client.read_text_file.assert_awaited_once_with("skills/b/refund-policy", "references/eu.md")

    @pytest.mark.asyncio
    async def test_rejects_reference_to_another_skill(self):
        reader, client = _reader()
        skill = make_resolved_skill(
            "skills/b/refund-policy", "refund-policy", files=("references/eu.md",)
        )

        with pytest.raises(SkillFileNotFoundError):
            await reader.read_bundled_file(skill, "skill://other/references/eu.md")
        client.read_text_file.assert_not_awaited()
