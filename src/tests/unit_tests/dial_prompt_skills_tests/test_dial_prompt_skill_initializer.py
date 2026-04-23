from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import (
    SkillCatastrophicInitializationException,
    SkillInitializationException,
)
from quickapp.config.skill import DialPromptSkillConfig
from quickapp.dial_prompt_skills import ResolvedDialPromptSkill, _DialPromptSkillsContext
from quickapp.dial_prompt_skills._dial_prompt_skill_initializer import _DialPromptSkillInitializer
from quickapp.dial_prompt_skills._dial_prompt_skill_resolver import DialPromptSkillResolverOutput
from quickapp.skills._skill_metadata import SkillMetadata


def _make_config_provider(skills: list[DialPromptSkillConfig] | None = None) -> MagicMock:
    config = MagicMock()
    config.skills = skills
    provider = MagicMock()
    provider.get.return_value = config
    return provider


def _resolved(url: str, name: str, content: str = "body") -> ResolvedDialPromptSkill:
    return ResolvedDialPromptSkill(
        url=url,
        metadata=SkillMetadata(name=name, description="d"),
        content=content,
    )


class TestDialPromptSkillInitializer:

    @pytest.mark.asyncio
    async def test_no_skills_is_noop(self):
        resolver = MagicMock()
        resolver.resolve = AsyncMock()
        context = _DialPromptSkillsContext()
        initializer = _DialPromptSkillInitializer(
            config_provider=_make_config_provider(skills=None),
            resolver=resolver,
            context=context,
        )

        await initializer.initialize()

        resolver.resolve.assert_not_awaited()
        assert context.resolved_skills == []
        assert context.exceptions == []

    @pytest.mark.asyncio
    async def test_empty_skills_is_noop(self):
        resolver = MagicMock()
        resolver.resolve = AsyncMock()
        context = _DialPromptSkillsContext()
        initializer = _DialPromptSkillInitializer(
            config_provider=_make_config_provider(skills=[]),
            resolver=resolver,
            context=context,
        )

        await initializer.initialize()

        resolver.resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_happy_path_populates_context(self):
        configs = [DialPromptSkillConfig(url="prompts/b/s1")]
        resolver = MagicMock()
        resolver.resolve = AsyncMock(
            return_value=DialPromptSkillResolverOutput(
                resolved=[_resolved("prompts/b/s1", "s1")],
                exceptions=[],
            )
        )
        context = _DialPromptSkillsContext()
        initializer = _DialPromptSkillInitializer(
            config_provider=_make_config_provider(skills=configs),
            resolver=resolver,
            context=context,
        )

        await initializer.initialize()

        resolver.resolve.assert_awaited_once_with(configs)
        assert len(context.resolved_skills) == 1
        assert context.resolved_skills[0].metadata.name == "s1"
        assert context.exceptions == []

    @pytest.mark.asyncio
    async def test_per_url_failures_flow_to_context(self):
        configs = [DialPromptSkillConfig(url="prompts/b/broken")]
        resolver = MagicMock()
        resolver.resolve = AsyncMock(
            return_value=DialPromptSkillResolverOutput(
                resolved=[],
                exceptions=[
                    SkillInitializationException(url="prompts/b/broken", reason="fetch failed")
                ],
            )
        )
        context = _DialPromptSkillsContext()
        initializer = _DialPromptSkillInitializer(
            config_provider=_make_config_provider(skills=configs),
            resolver=resolver,
            context=context,
        )

        await initializer.initialize()

        assert len(context.exceptions) == 1
        exc = context.exceptions[0]
        assert isinstance(exc, SkillInitializationException)
        assert not isinstance(exc, SkillCatastrophicInitializationException)
        assert exc.is_hard is False
        assert exc.url == "prompts/b/broken"

    @pytest.mark.asyncio
    async def test_resolver_exception_becomes_catastrophic(self):
        configs = [DialPromptSkillConfig(url="prompts/b/s1")]
        resolver = MagicMock()
        resolver.resolve = AsyncMock(side_effect=RuntimeError("DIAL Core is down"))
        context = _DialPromptSkillsContext()
        initializer = _DialPromptSkillInitializer(
            config_provider=_make_config_provider(skills=configs),
            resolver=resolver,
            context=context,
        )

        await initializer.initialize()

        assert context.resolved_skills == []
        assert len(context.exceptions) == 1
        exc = context.exceptions[0]
        assert isinstance(exc, SkillCatastrophicInitializationException)
        assert exc.is_hard is True
        assert "DIAL Core is down" in exc.reason
