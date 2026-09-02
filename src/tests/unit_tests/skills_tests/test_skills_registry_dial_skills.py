from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.dial_prompt_skills import _DialPromptSkillsContext
from quickapp.dial_skills import DialSkillReader, _DialSkillsContext
from quickapp.skills._exceptions import SkillFileNotFoundError, SkillFilesNotSupportedError
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills._skills_registry import SkillsRegistry
from tests.unit_tests.common.common import make_resolved_dial_prompt_skill as _prompt_skill
from tests.unit_tests.common.common import make_resolved_dial_skill as _dial_skill


def _make_predefined_provider(
    skills: list[SkillMetadata] | None = None,
    contents: dict[str, str] | None = None,
) -> MagicMock:
    provider = MagicMock()
    provider.get_all_skills.return_value = skills or []
    provider.get_all_skill_contents.return_value = contents or {}
    return provider


def _make_dial_skills(
    skills: list, read_result: str = "file body"
) -> tuple[_DialSkillsContext, DialSkillReader, MagicMock]:
    """Build the context/reader pair ``SkillsRegistry`` takes for DIAL skills."""
    client = MagicMock()
    client.read_text_file = AsyncMock(return_value=read_result)
    context = _DialSkillsContext()
    context.extend_resolved_skills(skills)
    return context, DialSkillReader(client), client


class TestMerge:

    @pytest.mark.asyncio
    async def test_dial_skill_appears_in_available_skills(self):
        context, _, _ = _make_dial_skills([_dial_skill("skills/b/refunds", "refunds")])
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            dial_skills_context=context,
        )

        xml = await registry.get_prompt_part()

        assert "refunds" in xml

    def test_predefined_wins_over_dial_skill(self):
        predefined = [SkillMetadata(name="shared", description="predefined")]
        context, _, _ = _make_dial_skills([_dial_skill("skills/b/shared", "shared")])
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(predefined, {"shared": "predefined"}),
            dial_skills_context=context,
        )

        assert registry.get_skill_content("shared") == "predefined"
        assert "same name as an already loaded skill" in context.exceptions[0].reason

    def test_dial_prompt_wins_over_dial_skill(self):
        prompt_context = _DialPromptSkillsContext()
        prompt_context.extend_resolved_skills(
            [_prompt_skill("prompts/b/shared", "shared", content="from prompt")]
        )
        dial_context, _, _ = _make_dial_skills([_dial_skill("skills/b/shared", "shared")])
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            dial_prompt_skills_context=prompt_context,
            dial_skills_context=dial_context,
        )

        assert registry.get_skill_content("shared") == "from prompt"
        assert dial_context.exceptions

    def test_all_three_sources_coexist(self):
        prompt_context = _DialPromptSkillsContext()
        prompt_context.extend_resolved_skills([_prompt_skill("prompts/b/p", "from-prompt")])
        dial_context, _, _ = _make_dial_skills([_dial_skill("skills/b/s", "from-skill")])
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(
                [SkillMetadata(name="predef", description="d")], {"predef": "body"}
            ),
            dial_prompt_skills_context=prompt_context,
            dial_skills_context=dial_context,
        )

        for name in ("predef", "from-prompt", "from-skill"):
            assert registry.get_skill_content(name)


class TestReadSkillFile:

    @pytest.mark.asyncio
    async def test_reads_an_advertised_file(self):
        skill = _dial_skill("skills/b/s", "s", files=("references/eu.md",))
        context, reader, _ = _make_dial_skills([skill], read_result="# EU rules")
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            dial_skills_context=context,
            dial_skill_reader=reader,
        )

        assert await registry.read_skill_file("s", "references/eu.md") == "# EU rules"

    @pytest.mark.asyncio
    async def test_unadvertised_path_is_refused_with_the_inventory(self):
        skill = _dial_skill("skills/b/s", "s", files=("references/eu.md",))
        context, reader, _ = _make_dial_skills([skill])
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            dial_skills_context=context,
            dial_skill_reader=reader,
        )

        with pytest.raises(SkillFileNotFoundError) as exc:
            await registry.read_skill_file("s", "assets/logo.png")

        assert "references/eu.md" in str(exc.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "../../../other-bucket/their-skill/files/SKILL.md",
            "/etc/passwd",
            ".env",
            "references/../../escape.md",
        ],
    )
    async def test_traversal_and_hidden_paths_are_refused(self, path: str):
        # Containment is inventory membership: nothing that was not advertised
        # can be reached, whatever its shape.
        skill = _dial_skill("skills/b/s", "s", files=("references/eu.md",))
        context, reader, _ = _make_dial_skills([skill])
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            dial_skills_context=context,
            dial_skill_reader=reader,
        )

        with pytest.raises(SkillFileNotFoundError):
            await registry.read_skill_file("s", path)

    @pytest.mark.asyncio
    async def test_manifest_path_returns_the_manifest(self):
        skill = _dial_skill("skills/b/s", "s", content="# Manifest", files=("a.md",))
        context, reader, _ = _make_dial_skills([skill])
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            dial_skills_context=context,
            dial_skill_reader=reader,
        )

        assert await registry.read_skill_file("s", "SKILL.md") == "# Manifest"

    @pytest.mark.asyncio
    async def test_predefined_skill_has_no_bundled_files(self):
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(
                [SkillMetadata(name="predef", description="d")], {"predef": "body"}
            ),
        )

        with pytest.raises(SkillFilesNotSupportedError, match="has no bundled files"):
            await registry.read_skill_file("predef", "references/eu.md")

    @pytest.mark.asyncio
    async def test_unknown_skill_raises(self):
        registry = SkillsRegistry(predefined_provider=_make_predefined_provider())

        with pytest.raises(FileNotFoundError, match="Skill not found"):
            await registry.read_skill_file("nope", "a.md")

    @pytest.mark.asyncio
    async def test_repeat_read_is_memoized(self):
        skill = _dial_skill("skills/b/s", "s", files=("a.md",))
        context, reader, client = _make_dial_skills([skill])
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            dial_skills_context=context,
            dial_skill_reader=reader,
        )

        await registry.read_skill_file("s", "a.md")
        await registry.read_skill_file("s", "a.md")

        assert client.read_text_file.await_count == 1
