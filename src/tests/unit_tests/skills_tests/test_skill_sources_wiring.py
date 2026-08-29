"""The `list[Skill]` multiprovider contract each source package implements.

Precedence lives in ``SkillsRegistry`` precisely so that a source which is not
installed - or is gated off behind ``ENABLE_PREVIEW_FEATURES`` - simply
contributes nothing, instead of leaving the registry with an unbound import.
"""

import pytest
from injector import Binder, Injector, Module, ProviderOf, multiprovider, singleton

from quickapp.dial_prompt_skills import _DialPromptSkill, _DialPromptSkillsContext
from quickapp.dial_skills._dial_skill import _DialSkill
from quickapp.dial_skills._dial_skills_context import _DialSkillsContext
from quickapp.skills._skill import Skill, SkillSourceKind
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills._skills_context import _SkillsContext
from quickapp.skills._skills_registry import SkillsRegistry
from tests.unit_tests.common.common import make_predefined_skill


class _PredefinedSource(Module):
    """Stands in for ``SkillsModule``'s predefined contribution."""

    @multiprovider
    def _provide(self) -> list[Skill]:
        return [make_predefined_skill("predefined", content="predefined body")]


class _PromptSource(Module):
    """``DialPromptSkillsModule`` reading its request-scoped context."""

    def configure(self, binder: Binder) -> None:
        context = _DialPromptSkillsContext()
        context.extend_resolved_skills(
            [
                _DialPromptSkill(
                    metadata=SkillMetadata(name="from-prompt", description="d"),
                    content="prompt body",
                    url="prompts/b/p",
                    config_index=1,
                )
            ]
        )
        binder.bind(_DialPromptSkillsContext, to=context, scope=singleton)

    @multiprovider
    def _provide(self, context: _DialPromptSkillsContext) -> list[Skill]:
        return list(context.resolved_skills)


class _DialSkillSource(Module):
    """``DialSkillsModule`` reading its request-scoped context."""

    def configure(self, binder: Binder) -> None:
        context = _DialSkillsContext()
        context.extend_resolved_skills(
            [
                _DialSkill(
                    metadata=SkillMetadata(name="from-skill", description="d"),
                    manifest="skill body",
                    files=[],
                    url="skills/b/s",
                    config_index=0,
                    client=None,  # type: ignore[arg-type]
                )
            ]
        )
        binder.bind(_DialSkillsContext, to=context, scope=singleton)

    @multiprovider
    def _provide(self, context: _DialSkillsContext) -> list[Skill]:
        return list(context.resolved_skills)


def _registry(modules: list[Module]) -> SkillsRegistry:
    injector = Injector(modules)
    return SkillsRegistry(
        skills_provider=injector.get(ProviderOf[list[Skill]]),
        context=_SkillsContext(),
    )


class TestSourceContributions:
    async def _names(self, registry: SkillsRegistry) -> list[str]:
        xml = await registry.get_prompt_part()
        return [
            line.strip()[6:-7] for line in xml.splitlines() if line.strip().startswith("<name>")
        ]

    @pytest.mark.asyncio
    async def test_every_installed_source_contributes(self):
        registry = _registry([_PredefinedSource(), _PromptSource(), _DialSkillSource()])

        assert await self._names(registry) == ["predefined", "from-skill", "from-prompt"]

    @pytest.mark.asyncio
    async def test_an_uninstalled_source_simply_contributes_nothing(self):
        registry = _registry([_PredefinedSource(), _PromptSource()])

        assert await self._names(registry) == ["predefined", "from-prompt"]

    @pytest.mark.asyncio
    async def test_only_predefined_still_works(self):
        registry = _registry([_PredefinedSource()])

        assert await self._names(registry) == ["predefined"]

    @pytest.mark.asyncio
    async def test_sources_keep_their_provenance_and_content(self):
        registry = _registry([_PredefinedSource(), _PromptSource(), _DialSkillSource()])
        await registry.get_prompt_part()

        assert registry.get_skill("predefined").read_manifest() == "predefined body"
        assert registry.get_skill("from-prompt").read_manifest() == "prompt body"
        assert registry.get_skill("from-skill").read_manifest() == "skill body"

    @pytest.mark.asyncio
    async def test_configured_sources_are_ordered_by_config_index_not_module_order(self):
        """`from-skill` is contributed last but configured first."""
        registry = _registry([_PredefinedSource(), _PromptSource(), _DialSkillSource()])

        names = await self._names(registry)

        assert names.index("from-skill") < names.index("from-prompt")


class TestSourceKinds:
    def test_each_implementation_reports_its_own_source(self):
        injector = Injector([_PredefinedSource(), _PromptSource(), _DialSkillSource()])

        by_name = {s.metadata.name: s.source for s in injector.get(list[Skill])}

        assert by_name == {
            "predefined": SkillSourceKind.PREDEFINED,
            "from-prompt": SkillSourceKind.DIAL_PROMPT,
            "from-skill": SkillSourceKind.DIAL_SKILL,
        }
