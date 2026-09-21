"""``_SkillInvocationInjector`` — a ``StagedToolSyntheticInjector`` on
``InjectionFrequency.APPEND_IF_CHANGED``."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.tool_names import INTERNAL_SKILLS_READ_SKILL_TOOL_NAME
from quickapp.config.application import StageDisplayLevel
from quickapp.skills.invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skills.invocation._skill_invocation_injector import _SkillInvocationInjector
from tests.unit_tests.common.common import make_resolved_skill as _skill

_URL = "skills/b/code-review"


def _skill_reader_tool(content: str = "the manifest") -> MagicMock:
    tool = MagicMock(spec=StagedBaseTool)
    tool.tool_config = MagicMock()
    tool.tool_config.open_ai_tool.function.name = INTERNAL_SKILLS_READ_SKILL_TOOL_NAME
    tool.arun = AsyncMock(
        return_value=ToolCallResult(content=content, content_type="text/markdown")
    )
    return tool


def _make(current: str | None, resolved: list = (), tool: MagicMock | None = None):
    context = _InvokedSkillsContext()
    context.set_current_pick_url(current)
    context.set_resolved_skills(list(resolved))

    enrichers_provider = MagicMock()
    enrichers_provider.get.return_value = []

    injector = _SkillInvocationInjector(
        context, [tool] if tool is not None else [], enrichers_provider
    )
    return injector, tool


def _args(message: Message) -> dict:
    return json.loads(message.tool_calls[0].function.arguments)


class TestInjection:

    @pytest.mark.asyncio
    async def test_no_pick_this_turn_leaves_the_messages_alone(self):
        injector, tool = _make(None, tool=_skill_reader_tool())
        messages = [Message(role=Role.USER, content="hi")]

        assert await injector.transform(messages) == messages
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_pair_goes_after_the_first_user_message(self):
        injector, _ = _make(_URL, [_skill(_URL, "code-review")], _skill_reader_tool())
        messages = [
            Message(role=Role.USER, content="/code-review …"),
            Message(role=Role.ASSISTANT, content="ok"),
            Message(role=Role.USER, content="and also …"),
        ]

        result = await injector.transform(messages)

        assert [m.role for m in result] == [
            Role.USER,
            Role.ASSISTANT,
            Role.TOOL,
            Role.ASSISTANT,
            Role.USER,
        ]
        assert _args(result[1]) == {"skill_name": "code-review"}
        assert result[2].content == "the manifest"
        assert result[2].tool_call_id == result[1].tool_calls[0].id

    @pytest.mark.asyncio
    async def test_the_skill_is_read_at_info_so_the_stage_is_shown(self):
        injector, tool = _make(_URL, [_skill(_URL, "code-review")], _skill_reader_tool())

        await injector.transform([Message(role=Role.USER, content="hi")])

        tool.arun.assert_awaited_once()
        assert tool.arun.await_args.kwargs["stage_level"] == StageDisplayLevel.INFO

    @pytest.mark.asyncio
    async def test_the_skill_name_is_passed_to_the_tool(self):
        injector, tool = _make(_URL, [_skill(_URL, "code-review")], _skill_reader_tool())

        await injector.transform([Message(role=Role.USER, content="hi")])

        assert tool.arun.await_args.kwargs["skill_name"] == "code-review"


class TestLaterTurns:

    @pytest.mark.asyncio
    async def test_nothing_is_injected_once_the_pick_is_no_longer_this_turns(self):
        injector, tool = _make(_URL, [_skill(_URL, "code-review")], _skill_reader_tool())
        first = await injector.transform([Message(role=Role.USER, content="hi")])

        # Next turn the chip is on an earlier message, so no pick is current.
        injector, tool = _make(None, [_skill(_URL, "code-review")], _skill_reader_tool())
        messages = [*first, Message(role=Role.USER, content="clarify?")]

        assert await injector.transform(messages) == messages
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_re_running_the_same_turn_does_not_duplicate_the_pair(self):
        injector, _ = _make(_URL, [_skill(_URL, "code-review")], _skill_reader_tool())
        first = await injector.transform([Message(role=Role.USER, content="hi")])

        second = await injector.transform(first)

        assert [m.role for m in second] == [m.role for m in first]


class TestFailedPick:

    @pytest.mark.asyncio
    async def test_an_unresolved_pick_gets_a_fixed_error_result_named_after_its_url(self):
        injector, tool = _make(_URL, tool=_skill_reader_tool())

        result = await injector.transform([Message(role=Role.USER, content="hi")])

        assert _args(result[1]) == {"skill_name": "code-review"}
        assert result[2].content == (
            "Error: the user's skill `code-review` could not be loaded."
            " The reason is shown to the user."
        )
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_missing_skill_reader_tool_injects_nothing(self):
        injector, _ = _make(_URL, [_skill(_URL, "code-review")])
        messages = [Message(role=Role.USER, content="hi")]

        assert await injector.transform(messages) == messages
