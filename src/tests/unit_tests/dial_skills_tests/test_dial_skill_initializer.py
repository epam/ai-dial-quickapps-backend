from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import (
    SkillCatastrophicInitializationException,
    SkillInitializationException,
)
from quickapp.config.skill import DialPromptSkillConfig, DialSkillConfig
from quickapp.dial_skills._dial_skill_initializer import _DialSkillInitializer
from quickapp.dial_skills._dial_skill_resolver import DialSkillResolverOutput
from quickapp.dial_skills._dial_skills_context import _DialSkillsContext
from tests.unit_tests.common.common import make_provider


def _config_provider(skills: list | None) -> MagicMock:
    config = MagicMock()
    config.skills = skills
    return make_provider(config)


def _initializer(
    skills: list | None,
    output: DialSkillResolverOutput | None = None,
    side_effect: Exception | None = None,
) -> tuple[_DialSkillInitializer, MagicMock, _DialSkillsContext]:
    resolver = MagicMock()
    resolver.resolve = AsyncMock(
        side_effect=side_effect,
        return_value=output or DialSkillResolverOutput(resolved=[], exceptions=[]),
    )
    context = _DialSkillsContext()
    return (
        _DialSkillInitializer(
            config_provider=_config_provider(skills),
            resolver=resolver,
            context=context,
        ),
        resolver,
        context,
    )


class TestDialSkillInitializer:
    @pytest.mark.asyncio
    async def test_no_skills_configured_skips_resolution(self):
        initializer, resolver, _ = _initializer(None)

        await initializer.initialize()

        resolver.resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_only_other_skill_types_configured_skips_resolution(self):
        initializer, resolver, _ = _initializer([DialPromptSkillConfig(url="prompts/b/p")])

        await initializer.initialize()

        resolver.resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_config_positions_survive_the_type_split(self):
        """Indices come from the whole `skills` list, not from this type's
        slice of it — cross-source precedence is ordered by them."""
        initializer, resolver, _ = _initializer(
            [
                DialPromptSkillConfig(url="prompts/b/p"),
                DialSkillConfig(url="skills/b/s"),
            ]
        )

        await initializer.initialize()

        (indexed,) = resolver.resolve.await_args.args
        assert [index for index, _ in indexed] == [1]

    @pytest.mark.asyncio
    async def test_resolver_output_flows_into_the_context(self):
        exception = SkillInitializationException(url="skills/b/bad", reason="boom")
        initializer, _, context = _initializer(
            [DialSkillConfig(url="skills/b/s")],
            output=DialSkillResolverOutput(resolved=[], exceptions=[exception]),
        )

        await initializer.initialize()

        assert context.exceptions == [exception]

    @pytest.mark.asyncio
    async def test_a_resolver_crash_becomes_a_catastrophic_exception(self):
        initializer, _, context = _initializer(
            [DialSkillConfig(url="skills/b/s")],
            side_effect=RuntimeError("resolver died"),
        )

        await initializer.initialize()

        assert len(context.exceptions) == 1
        catastrophic = context.exceptions[0]
        assert isinstance(catastrophic, SkillCatastrophicInitializationException)
        assert catastrophic.is_hard is True
        assert "resolver died" in catastrophic.reason
