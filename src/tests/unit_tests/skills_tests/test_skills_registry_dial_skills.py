from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.dial_prompt_skills import _DialPromptSkillsContext
from quickapp.dial_prompt_skills._dial_prompt_skills_source import _DialPromptSkillsSource
from quickapp.dial_skills import DialSkillReader, _DialSkillsContext
from quickapp.dial_skills._dial_skills_source import _DialSkillsSource
from quickapp.skills._exceptions import SkillFileNotFoundError, SkillFilesNotSupportedError
from quickapp.skills._predefined_skills_source import _PredefinedSkillsSource
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from tests.unit_tests.common.common import make_resolved_dial_prompt_skill as _prompt_skill
from tests.unit_tests.common.common import make_resolved_dial_skill as _dial_skill


def _predefined_source(
    skills: list[SkillMetadata] | None = None,
    contents: dict[str, str] | None = None,
) -> _PredefinedSkillsSource:
    provider = MagicMock(spec=AgentSkillsProvider)
    provider.get_all_skills.return_value = skills or []
    provider.get_all_skill_contents.return_value = contents or {}
    return _PredefinedSkillsSource(provider)


def _dial_skills_source(
    skills: list, read_result: str = "file body"
) -> tuple[_DialSkillsSource, _DialSkillsContext, MagicMock]:
    """Build the source/context/client trio for a ``_DialSkillsSource`` fixture."""
    client = MagicMock()
    client.read_text_file = AsyncMock(return_value=read_result)
    context = _DialSkillsContext()
    context.extend_resolved_skills(skills)
    return _DialSkillsSource(context, DialSkillReader(client)), context, client


class TestMerge:

    @pytest.mark.asyncio
    async def test_dial_skill_appears_in_available_skills(self):
        dial_source, _, _ = _dial_skills_source([_dial_skill("skills/b/refunds", "refunds")])
        registry = SkillsRegistry(sources=[_predefined_source(), dial_source])

        xml = await registry.get_prompt_part()

        assert "refunds" in xml

    def test_predefined_wins_over_dial_skill(self):
        predefined = [SkillMetadata(name="shared", description="predefined")]
        predefined_source = _predefined_source(predefined, {"shared": "predefined"})
        dial_source, dial_context, _ = _dial_skills_source(
            [_dial_skill("skills/b/shared", "shared")]
        )
        registry = SkillsRegistry(sources=[predefined_source, dial_source])

        assert registry.get_skill_content("shared") == "predefined"
        assert "already provided by predefined skills" in dial_context.exceptions[0].reason

    def test_dial_prompt_wins_over_dial_skill(self):
        prompt_context = _DialPromptSkillsContext()
        prompt_context.extend_resolved_skills(
            [_prompt_skill("prompts/b/shared", "shared", content="from prompt")]
        )
        prompt_source = _DialPromptSkillsSource(prompt_context)
        dial_source, dial_context, _ = _dial_skills_source(
            [_dial_skill("skills/b/shared", "shared")]
        )
        registry = SkillsRegistry(sources=[_predefined_source(), prompt_source, dial_source])

        assert registry.get_skill_content("shared") == "from prompt"
        assert "already provided by DIAL prompt skills" in dial_context.exceptions[0].reason

    def test_all_three_sources_coexist(self):
        prompt_context = _DialPromptSkillsContext()
        prompt_context.extend_resolved_skills([_prompt_skill("prompts/b/p", "from-prompt")])
        prompt_source = _DialPromptSkillsSource(prompt_context)
        dial_source, _, _ = _dial_skills_source([_dial_skill("skills/b/s", "from-skill")])
        predefined_source = _predefined_source(
            [SkillMetadata(name="predef", description="d")], {"predef": "body"}
        )
        registry = SkillsRegistry(sources=[predefined_source, prompt_source, dial_source])

        for name in ("predef", "from-prompt", "from-skill"):
            assert registry.get_skill_content(name)

    def test_precedence_is_independent_of_source_list_order(self):
        predefined = [SkillMetadata(name="shared", description="predefined")]
        predefined_source = _predefined_source(predefined, {"shared": "predefined"})
        dial_source, _, _ = _dial_skills_source([_dial_skill("skills/b/shared", "shared")])

        forward = SkillsRegistry(sources=[predefined_source, dial_source])
        reversed_order = SkillsRegistry(sources=[dial_source, predefined_source])

        assert forward.get_skill_content("shared") == "predefined"
        assert reversed_order.get_skill_content("shared") == "predefined"


class TestReadSkillFile:

    @pytest.mark.asyncio
    async def test_reads_an_advertised_file(self):
        skill = _dial_skill("skills/b/s", "s", files=("references/eu.md",))
        dial_source, _, _ = _dial_skills_source([skill], read_result="# EU rules")
        registry = SkillsRegistry(sources=[dial_source])

        assert await registry.read_skill_file("s", "references/eu.md") == "# EU rules"

    @pytest.mark.asyncio
    async def test_unadvertised_path_is_refused_with_the_inventory(self):
        skill = _dial_skill("skills/b/s", "s", files=("references/eu.md",))
        dial_source, _, _ = _dial_skills_source([skill])
        registry = SkillsRegistry(sources=[dial_source])

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
        dial_source, _, _ = _dial_skills_source([skill])
        registry = SkillsRegistry(sources=[dial_source])

        with pytest.raises(SkillFileNotFoundError):
            await registry.read_skill_file("s", path)

    @pytest.mark.asyncio
    async def test_manifest_path_returns_the_manifest(self):
        skill = _dial_skill("skills/b/s", "s", content="# Manifest", files=("a.md",))
        dial_source, _, _ = _dial_skills_source([skill])
        registry = SkillsRegistry(sources=[dial_source])

        assert await registry.read_skill_file("s", "SKILL.md") == "# Manifest"

    @pytest.mark.asyncio
    async def test_predefined_skill_has_no_bundled_files(self):
        predefined_source = _predefined_source(
            [SkillMetadata(name="predef", description="d")], {"predef": "body"}
        )
        registry = SkillsRegistry(sources=[predefined_source])

        with pytest.raises(SkillFilesNotSupportedError, match="has no bundled files"):
            await registry.read_skill_file("predef", "references/eu.md")

    @pytest.mark.asyncio
    async def test_unknown_skill_raises(self):
        registry = SkillsRegistry(sources=[])

        with pytest.raises(FileNotFoundError, match="Skill not found"):
            await registry.read_skill_file("nope", "a.md")

    @pytest.mark.asyncio
    async def test_repeat_read_is_memoized(self):
        skill = _dial_skill("skills/b/s", "s", files=("a.md",))
        dial_source, _, client = _dial_skills_source([skill])
        registry = SkillsRegistry(sources=[dial_source])

        await registry.read_skill_file("s", "a.md")
        await registry.read_skill_file("s", "a.md")

        assert client.read_text_file.await_count == 1
