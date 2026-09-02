from unittest.mock import MagicMock

import pytest

from quickapp.common.exceptions import SkillInitializationException
from quickapp.dial_prompt_skills import _DialPromptSkillsContext
from quickapp.dial_prompt_skills._dial_prompt_skills_source import _DialPromptSkillsSource
from quickapp.skills._predefined_skills_source import _PredefinedSkillsSource
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from tests.unit_tests.common.common import make_resolved_dial_prompt_skill as _resolved


def _predefined_source(
    skills: list[SkillMetadata] | None = None,
    contents: dict[str, str] | None = None,
) -> _PredefinedSkillsSource:
    provider = MagicMock(spec=AgentSkillsProvider)
    provider.get_all_skills.return_value = skills or []
    provider.get_all_skill_contents.return_value = contents or {}
    return _PredefinedSkillsSource(provider)


def _skill(name: str, description: str = "A skill") -> SkillMetadata:
    return SkillMetadata(name=name, description=description)


class TestSkillsRegistryNoContext:
    """Preview off: no dial-prompt source is contributed."""

    @pytest.mark.asyncio
    async def test_returns_predefined_only(self):
        predefined = [_skill("predefined-skill")]
        contents = {"predefined-skill": "# Predefined\nContent here"}
        registry = SkillsRegistry(sources=[_predefined_source(predefined, contents)])

        xml = await registry.get_prompt_part()

        assert "predefined-skill" in xml
        assert "<available_skills>" in xml

    def test_get_skill_content_returns_predefined(self):
        contents = {"my-skill": "# My Skill\nContent"}
        registry = SkillsRegistry(sources=[_predefined_source([_skill("my-skill")], contents)])

        assert registry.get_skill_content("my-skill") == "# My Skill\nContent"

    def test_get_skill_content_unknown_raises(self):
        registry = SkillsRegistry(sources=[_predefined_source()])

        with pytest.raises(FileNotFoundError, match="Skill not found"):
            registry.get_skill_content("nonexistent")

    @pytest.mark.asyncio
    async def test_empty_predefined_returns_empty_xml(self):
        registry = SkillsRegistry(sources=[_predefined_source()])

        assert await registry.get_prompt_part() == ""


class TestSkillsRegistryWithContext:
    """Preview on: a dial-prompt source is contributed and pre-populated."""

    @pytest.mark.asyncio
    async def test_merges_predefined_and_context_skills(self):
        predefined = [_skill("predefined")]
        contents = {"predefined": "Predefined content"}

        context = _DialPromptSkillsContext()
        context.extend_resolved_skills(
            [_resolved("prompts/b/dial-skill", "dial-skill", "From DIAL", "DIAL skill content")]
        )

        registry = SkillsRegistry(
            sources=[_predefined_source(predefined, contents), _DialPromptSkillsSource(context)]
        )

        xml = await registry.get_prompt_part()

        assert "predefined" in xml
        assert "dial-skill" in xml

    @pytest.mark.asyncio
    async def test_predefined_wins_on_name_collision_and_appends_exception(self):
        predefined = [_skill("shared-name", "Predefined version")]
        contents = {"shared-name": "Predefined content"}

        context = _DialPromptSkillsContext()
        context.extend_resolved_skills(
            [_resolved("prompts/b/collides", "shared-name", "DIAL version", "DIAL content")]
        )

        registry = SkillsRegistry(
            sources=[_predefined_source(predefined, contents), _DialPromptSkillsSource(context)]
        )

        xml = await registry.get_prompt_part()
        assert "Predefined version" in xml
        assert registry.get_skill_content("shared-name") == "Predefined content"

        assert len(context.exceptions) == 1
        collision = context.exceptions[0]
        assert isinstance(collision, SkillInitializationException)
        assert collision.url == "prompts/b/collides"
        assert "already provided by predefined skills" in collision.reason

    @pytest.mark.asyncio
    async def test_get_skill_content_for_context_skill(self):
        context = _DialPromptSkillsContext()
        context.extend_resolved_skills(
            [_resolved("prompts/b/only", "dial-only", content="DIAL prompt skill content")]
        )

        registry = SkillsRegistry(sources=[_predefined_source(), _DialPromptSkillsSource(context)])

        assert registry.get_skill_content("dial-only") == "DIAL prompt skill content"

    @pytest.mark.asyncio
    async def test_merge_caches_result(self):
        """Repeated calls must not re-run the merge (and so must not re-append
        collision warnings)."""
        predefined = [_skill("shared")]
        contents = {"shared": "Predefined content"}

        context = _DialPromptSkillsContext()
        context.extend_resolved_skills(
            [_resolved("prompts/b/collides", "shared", "DIAL version", "DIAL content")]
        )

        registry = SkillsRegistry(
            sources=[_predefined_source(predefined, contents), _DialPromptSkillsSource(context)]
        )

        await registry.get_prompt_part()
        await registry.get_prompt_part()
        registry.get_skill_content("shared")

        assert len(context.exceptions) == 1

    @pytest.mark.asyncio
    async def test_context_exceptions_preserved_through_merge(self):
        """Pre-existing per-URL exceptions in the context are not lost by
        the registry's merge."""
        context = _DialPromptSkillsContext()
        context.append_exception(
            SkillInitializationException(url="prompts/b/broken", reason="Fetch failed")
        )

        registry = SkillsRegistry(sources=[_predefined_source(), _DialPromptSkillsSource(context)])

        await registry.get_prompt_part()
        assert len(context.exceptions) == 1
        assert context.exceptions[0].url == "prompts/b/broken"
