import pytest

from quickapp.common.exceptions import SkillInitializationException
from quickapp.dial_prompt_skills import _DialPromptSkillsContext
from quickapp.skills._exceptions import SkillFileNotFound
from quickapp.skills._skill import Skill
from quickapp.skills._skills_context import _SkillsContext
from quickapp.skills._skills_registry import SkillsRegistry
from tests.unit_tests.common.common import make_predefined_skill as _predefined
from tests.unit_tests.common.common import make_provider
from tests.unit_tests.common.common import make_resolved_dial_prompt_skill as _resolved


def _registry(
    skills: list[Skill] | None = None,
    context: _SkillsContext | None = None,
) -> SkillsRegistry:
    """Build a registry over the source-neutral ``list[Skill]`` the modules contribute."""
    return SkillsRegistry(
        skills_provider=make_provider(skills or []),
        context=context or _SkillsContext(),
    )


class TestSkillsRegistryNoContext:
    """No configured skills: predefined are the only source contributing."""

    @pytest.mark.asyncio
    async def test_returns_predefined_only(self):
        registry = _registry(
            [_predefined("predefined-skill", content="# Predefined\nContent here")]
        )

        xml = await registry.get_prompt_part()

        assert "predefined-skill" in xml
        assert "<available_skills>" in xml

    def test_get_skill_content_returns_predefined(self):
        registry = _registry([_predefined("my-skill", content="# My Skill\nContent")])

        assert registry.get_skill("my-skill").read_manifest() == "# My Skill\nContent"

    def test_get_skill_content_unknown_raises(self):
        registry = _registry()

        with pytest.raises(SkillFileNotFound, match="Skill not found"):
            registry.get_skill("nonexistent")

    @pytest.mark.asyncio
    async def test_empty_predefined_returns_empty_xml(self):
        registry = _registry()

        assert await registry.get_prompt_part() == ""


class TestSkillsRegistryWithContext:
    """Configured skills present alongside predefined ones."""

    @pytest.mark.asyncio
    async def test_merges_predefined_and_context_skills(self):
        registry = _registry(
            [
                _predefined("predefined", content="Predefined content"),
                _resolved("prompts/b/dial-skill", "dial-skill", "From DIAL", "DIAL skill content"),
            ]
        )

        xml = await registry.get_prompt_part()

        assert "predefined" in xml
        assert "dial-skill" in xml

    @pytest.mark.asyncio
    async def test_predefined_wins_on_name_collision_and_appends_exception(self):
        context = _SkillsContext()
        registry = _registry(
            [
                _predefined("shared-name", "Predefined version", "Predefined content"),
                _resolved("prompts/b/collides", "shared-name", "DIAL version", "DIAL content"),
            ],
            context=context,
        )

        xml = await registry.get_prompt_part()
        assert "Predefined version" in xml
        assert registry.get_skill("shared-name").read_manifest() == "Predefined content"

        assert len(context.exceptions) == 1
        collision = context.exceptions[0]
        assert isinstance(collision, SkillInitializationException)
        assert collision.url == "prompts/b/collides"
        assert "predefined" in collision.reason.lower()

    @pytest.mark.asyncio
    async def test_get_skill_content_for_context_skill(self):
        registry = _registry(
            [_resolved("prompts/b/only", "dial-only", content="DIAL prompt skill content")]
        )

        assert registry.get_skill("dial-only").read_manifest() == "DIAL prompt skill content"

    @pytest.mark.asyncio
    async def test_merge_caches_result(self):
        """Repeated calls must not re-run the merge (and so must not re-append
        collision warnings)."""
        context = _SkillsContext()
        registry = _registry(
            [
                _predefined("shared", content="Predefined content"),
                _resolved("prompts/b/collides", "shared", "DIAL version", "DIAL content"),
            ],
            context=context,
        )

        await registry.get_prompt_part()
        await registry.get_prompt_part()
        registry.get_skill("shared")

        assert len(context.exceptions) == 1

    @pytest.mark.asyncio
    async def test_context_exceptions_preserved_through_merge(self):
        """A source context's own per-URL exceptions are untouched by the merge —
        each source module contributes them independently of the registry."""
        source_context = _DialPromptSkillsContext()
        source_context.append_exception(
            SkillInitializationException(url="prompts/b/broken", reason="Fetch failed")
        )

        registry = _registry()

        await registry.get_prompt_part()
        assert len(source_context.exceptions) == 1
        assert source_context.exceptions[0].url == "prompts/b/broken"


class TestConfiguredSkillPrecedence:
    """Rules the registry owns because it is the only component that sees every source."""

    @pytest.mark.asyncio
    async def test_lowest_config_index_wins_among_configured(self):
        context = _SkillsContext()
        registry = _registry(
            [
                _resolved("prompts/b/second", "dup", content="second", config_index=3),
                _resolved("prompts/b/first", "dup", content="first", config_index=1),
            ],
            context=context,
        )

        await registry.get_prompt_part()

        assert registry.get_skill("dup").read_manifest() == "first"
        assert [e.url for e in context.exceptions] == ["prompts/b/second"]
        assert "earlier configured skill" in context.exceptions[0].reason

    @pytest.mark.asyncio
    async def test_predefined_beats_a_lower_config_index(self):
        """Predefined precedence is absolute — config position never overrides it."""
        context = _SkillsContext()
        registry = _registry(
            [
                _predefined("shared", content="predefined body"),
                _resolved("prompts/b/first", "shared", content="configured", config_index=0),
            ],
            context=context,
        )

        await registry.get_prompt_part()

        assert registry.get_skill("shared").read_manifest() == "predefined body"
        assert len(context.exceptions) == 1
