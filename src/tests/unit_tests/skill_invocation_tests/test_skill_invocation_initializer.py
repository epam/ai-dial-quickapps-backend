"""``_SkillInvocationInitializer`` — collect chips, cap, delegate, report this turn."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.exceptions import SkillInitializationException
from quickapp.dial_skills._dial_skill_resolver import DialSkillResolver, DialSkillResolverOutput
from quickapp.skill_invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skill_invocation._settings import SkillInvocationSettings
from quickapp.skill_invocation._skill_invocation_initializer import _SkillInvocationInitializer
from tests.unit_tests.common.common import make_resolved_skill as _skill


def _user(*urls: str) -> Message:
    return Message.model_validate(
        {
            "role": "user",
            "content": "hi",
            "custom_content": {"skills": [{"url": url} for url in urls]},
        }
    )


def _make(
    messages: list[Message], output: DialSkillResolverOutput | None = None, max_skills: int = 10
):
    resolver = MagicMock(spec=DialSkillResolver)
    resolver.resolve = AsyncMock(
        return_value=output or DialSkillResolverOutput(resolved=[], exceptions=[])
    )
    context = _InvokedSkillsContext()
    settings = SkillInvocationSettings(SKILL_INVOCATION_MAX_SKILLS=max_skills)
    return _SkillInvocationInitializer(messages, resolver, context, settings), resolver, context


class TestInitialize:

    @pytest.mark.asyncio
    async def test_no_chips_skips_resolution_entirely(self):
        initializer, resolver, context = _make([Message(role=Role.USER, content="hi")])

        await initializer.initialize()

        resolver.resolve.assert_not_awaited()
        assert context.resolved_skills == []
        assert context.current_turn_urls == []

    @pytest.mark.asyncio
    async def test_resolves_every_pick_in_the_conversation_oldest_first(self):
        initializer, resolver, _ = _make([_user("skills/b/a"), _user("skills/b/z")])

        await initializer.initialize()

        configs = resolver.resolve.await_args.args[0]
        assert [cfg.url for cfg in configs] == ["skills/b/a", "skills/b/z"]

    @pytest.mark.asyncio
    async def test_the_cap_drops_the_oldest_picks(self):
        initializer, resolver, _ = _make([_user("skills/b/a"), _user("skills/b/z")], max_skills=1)

        await initializer.initialize()

        assert [cfg.url for cfg in resolver.resolve.await_args.args[0]] == ["skills/b/z"]

    @pytest.mark.asyncio
    async def test_records_the_chips_of_the_message_being_answered(self):
        initializer, _, context = _make(
            [_user("skills/b/a"), Message(role=Role.ASSISTANT, content="ok"), _user("skills/b/z")]
        )

        await initializer.initialize()

        assert context.current_turn_urls == ["skills/b/z"]

    @pytest.mark.asyncio
    async def test_registers_what_resolved(self):
        skill = _skill("skills/b/a", "a")
        initializer, _, context = _make(
            [_user("skills/b/a")],
            DialSkillResolverOutput(resolved=[skill], exceptions=[]),
        )

        await initializer.initialize()

        assert context.find_skill("skills/b/a") is not None

    @pytest.mark.asyncio
    async def test_a_resolver_crash_is_reported_and_does_not_raise(self):
        initializer, resolver, context = _make([_user("skills/b/a")])
        resolver.resolve = AsyncMock(side_effect=RuntimeError("boom"))

        await initializer.initialize()

        assert len(context.exceptions) == 1
        assert "Failed to resolve user skills" in str(context.exceptions[0])


class TestReporting:

    @pytest.mark.asyncio
    async def test_only_this_turns_problems_reach_initialization_issues(self):
        initializer, _, context = _make(
            [_user("skills/b/old"), _user("skills/b/new")],
            DialSkillResolverOutput(
                resolved=[],
                exceptions=[
                    SkillInitializationException(url="skills/b/old", reason="stale"),
                    SkillInitializationException(url="skills/b/new", reason="fresh"),
                ],
            ),
        )

        await initializer.initialize()

        assert [exc.reason for exc in context.exceptions] == ["fresh"]

    @pytest.mark.asyncio
    async def test_an_exception_without_a_url_is_always_reported(self):
        initializer, _, context = _make(
            [_user("skills/b/a")],
            DialSkillResolverOutput(
                resolved=[], exceptions=[SkillInitializationException(reason="global")]
            ),
        )

        await initializer.initialize()

        assert [exc.reason for exc in context.exceptions] == ["global"]
