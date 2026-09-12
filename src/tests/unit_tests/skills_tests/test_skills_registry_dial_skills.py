from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.dial_prompt_skills import _DialPromptSkillsContext
from quickapp.dial_skills import DialSkillReader, _DialSkillsContext
from quickapp.skills._exceptions import SkillFileNotFoundError, SkillFilesNotSupportedError
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from tests.unit_tests.common.common import make_resolved_skill as _skill


def _predefined_provider(
    skills: list[SkillMetadata] | None = None,
    contents: dict[str, str] | None = None,
) -> MagicMock:
    skills = skills or []
    contents = contents or {}
    provider = MagicMock(spec=AgentSkillsProvider)
    provider.order = AgentSkillsProvider.order
    provider.display_name = AgentSkillsProvider.display_name
    provider.resolved_skills = [
        _skill(f"predefined:{m.name}", m.name, m.description, contents[m.name]) for m in skills
    ]
    return provider


def _dial_skills_context(
    urls_and_names: list[tuple[str, str]],
    read_result: str = "file body",
    content: str = "body",
    files: tuple[str, ...] = (),
) -> tuple[_DialSkillsContext, MagicMock]:
    """A dial-skills context whose skills carry a real (client-mocked) reader."""
    client = MagicMock()
    client.read_text_file = AsyncMock(return_value=read_result)
    reader = DialSkillReader(client)
    context = _DialSkillsContext()
    context.extend_resolved_skills(
        [
            _skill(url, name, content=content, files=files, reader=reader)
            for url, name in urls_and_names
        ]
    )
    return context, client


class TestMerge:

    @pytest.mark.asyncio
    async def test_dial_skill_appears_in_available_skills(self):
        dial_context, _ = _dial_skills_context([("skills/b/refunds", "refunds")])
        registry = SkillsRegistry(providers=[_predefined_provider(), dial_context])

        xml = await registry.get_prompt_part()

        assert "refunds" in xml

    def test_predefined_wins_over_dial_skill(self):
        predefined = [SkillMetadata(name="shared", description="predefined")]
        predefined_provider = _predefined_provider(predefined, {"shared": "predefined"})
        dial_context, _ = _dial_skills_context([("skills/b/shared", "shared")])
        registry = SkillsRegistry(providers=[predefined_provider, dial_context])

        assert registry.get_skill_content("shared") == "predefined"
        assert "already provided by predefined skills" in registry.collision_exceptions[0].reason

    def test_dial_prompt_wins_over_dial_skill(self):
        prompt_context = _DialPromptSkillsContext()
        prompt_context.extend_resolved_skills(
            [_skill("prompts/b/shared", "shared", content="from prompt")]
        )
        dial_context, _ = _dial_skills_context([("skills/b/shared", "shared")])
        registry = SkillsRegistry(providers=[_predefined_provider(), prompt_context, dial_context])

        assert registry.get_skill_content("shared") == "from prompt"
        assert "already provided by DIAL prompt skills" in registry.collision_exceptions[0].reason

    def test_all_three_providers_coexist(self):
        prompt_context = _DialPromptSkillsContext()
        prompt_context.extend_resolved_skills([_skill("prompts/b/p", "from-prompt")])
        dial_context, _ = _dial_skills_context([("skills/b/s", "from-skill")])
        predefined_provider = _predefined_provider(
            [SkillMetadata(name="predef", description="d")], {"predef": "body"}
        )
        registry = SkillsRegistry(providers=[predefined_provider, prompt_context, dial_context])

        for name in ("predef", "from-prompt", "from-skill"):
            assert registry.get_skill_content(name)

    def test_precedence_is_independent_of_provider_list_order(self):
        predefined = [SkillMetadata(name="shared", description="predefined")]
        predefined_provider = _predefined_provider(predefined, {"shared": "predefined"})
        dial_context, _ = _dial_skills_context([("skills/b/shared", "shared")])

        forward = SkillsRegistry(providers=[predefined_provider, dial_context])
        reversed_order = SkillsRegistry(providers=[dial_context, predefined_provider])

        assert forward.get_skill_content("shared") == "predefined"
        assert reversed_order.get_skill_content("shared") == "predefined"


class TestReadSkillFile:

    @pytest.mark.asyncio
    async def test_reads_an_advertised_file(self):
        dial_context, _ = _dial_skills_context(
            [("skills/b/s", "s")], read_result="# EU rules", files=("references/eu.md",)
        )
        registry = SkillsRegistry(providers=[dial_context])

        assert await registry.read_skill_file("s", "references/eu.md") == "# EU rules"

    @pytest.mark.asyncio
    async def test_unadvertised_path_is_refused_with_the_inventory(self):
        dial_context, _ = _dial_skills_context([("skills/b/s", "s")], files=("references/eu.md",))
        registry = SkillsRegistry(providers=[dial_context])

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
        dial_context, _ = _dial_skills_context([("skills/b/s", "s")], files=("references/eu.md",))
        registry = SkillsRegistry(providers=[dial_context])

        with pytest.raises(SkillFileNotFoundError):
            await registry.read_skill_file("s", path)

    @pytest.mark.asyncio
    async def test_manifest_path_returns_the_manifest(self):
        dial_context, _ = _dial_skills_context(
            [("skills/b/s", "s")], content="# Manifest", files=("a.md",)
        )
        registry = SkillsRegistry(providers=[dial_context])

        assert await registry.read_skill_file("s", "SKILL.md") == "# Manifest"

    @pytest.mark.asyncio
    async def test_predefined_skill_has_no_bundled_files(self):
        predefined_provider = _predefined_provider(
            [SkillMetadata(name="predef", description="d")], {"predef": "body"}
        )
        registry = SkillsRegistry(providers=[predefined_provider])

        with pytest.raises(SkillFilesNotSupportedError, match="has no bundled files"):
            await registry.read_skill_file("predef", "references/eu.md")

    @pytest.mark.asyncio
    async def test_unknown_skill_raises(self):
        registry = SkillsRegistry(providers=[])

        with pytest.raises(FileNotFoundError, match="Skill not found"):
            await registry.read_skill_file("nope", "a.md")

    @pytest.mark.asyncio
    async def test_repeat_read_is_memoized(self):
        dial_context, client = _dial_skills_context([("skills/b/s", "s")], files=("a.md",))
        registry = SkillsRegistry(providers=[dial_context])

        await registry.read_skill_file("s", "a.md")
        await registry.read_skill_file("s", "a.md")

        assert client.read_text_file.await_count == 1
