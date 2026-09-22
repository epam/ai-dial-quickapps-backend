"""``_SkillInvocationInjector`` — a ``MultiSyntheticToolCallInjector`` that turns the
chips of the current message into one parallel ``read_skill`` turn."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.tool_names import INTERNAL_SKILLS_READ_SKILL_TOOL_NAME
from quickapp.config.application import StageDisplayLevel
from quickapp.skill_invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skill_invocation._skill_invocation_injector import _SkillInvocationInjector
from tests.unit_tests.common.common import make_resolved_skill as _skill

_URL = "skills/b/code-review"
_URL2 = "skills/b/report-style"


def _skill_reader_tool(content: str = "the manifest") -> MagicMock:
    tool = MagicMock(spec=StagedBaseTool)
    tool.tool_config = MagicMock()
    tool.tool_config.open_ai_tool.function.name = INTERNAL_SKILLS_READ_SKILL_TOOL_NAME
    tool.arun = AsyncMock(
        side_effect=lambda *args, **kwargs: ToolCallResult(
            content=f"{content} for {kwargs['skill_name']}",
            content_type="text/markdown",
        )
    )
    return tool


def _make(current: list[str], resolved: list = (), tool: MagicMock | None = None):
    context = _InvokedSkillsContext()
    context.set_current_pick_urls(current)
    context.set_resolved_skills(list(resolved))

    enrichers_provider = MagicMock()
    enrichers_provider.get.return_value = []

    injector = _SkillInvocationInjector(
        context, [tool] if tool is not None else [], enrichers_provider
    )
    return injector, tool


def _args(message: Message, call_index: int = 0) -> dict:
    return json.loads(message.tool_calls[call_index].function.arguments)


class TestInjection:

    @pytest.mark.asyncio
    async def test_no_pick_this_turn_leaves_the_messages_alone(self):
        injector, tool = _make([], tool=_skill_reader_tool())
        messages = [Message(role=Role.USER, content="hi")]

        assert await injector.transform(messages) == messages
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_turn_goes_after_the_first_user_message(self):
        injector, _ = _make([_URL], [_skill(_URL, "code-review")], _skill_reader_tool())
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
        assert result[2].content == "the manifest for code-review"
        assert result[2].tool_call_id == result[1].tool_calls[0].id

    @pytest.mark.asyncio
    async def test_multiple_picks_produce_one_assistant_message_with_parallel_calls(self):
        injector, tool = _make(
            [_URL, _URL2],
            [_skill(_URL, "code-review"), _skill(_URL2, "report-style")],
            _skill_reader_tool(),
        )

        result = await injector.transform([Message(role=Role.USER, content="hi")])

        assert [m.role for m in result] == [Role.USER, Role.ASSISTANT, Role.TOOL, Role.TOOL]
        assistant = result[1]
        assert len(assistant.tool_calls) == 2
        assert _args(assistant, 0) == {"skill_name": "code-review"}
        assert _args(assistant, 1) == {"skill_name": "report-style"}

        tool_ids = {tc.id for tc in assistant.tool_calls}
        assert {result[2].tool_call_id, result[3].tool_call_id} == tool_ids
        assert {result[2].content, result[3].content} == {
            "the manifest for code-review",
            "the manifest for report-style",
        }
        assert tool.arun.await_count == 2

    @pytest.mark.asyncio
    async def test_a_mix_of_resolved_and_failed_picks_are_both_injected(self):
        injector, tool = _make([_URL, _URL2], [_skill(_URL, "code-review")], _skill_reader_tool())

        result = await injector.transform([Message(role=Role.USER, content="hi")])

        assert result[2].content == "the manifest for code-review"
        assert result[3].content == (
            "Error: the user's skill `report-style` could not be loaded."
            " The reason is shown to the user."
        )
        tool.arun.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_the_skill_is_read_at_info_so_the_stage_is_shown(self):
        injector, tool = _make([_URL], [_skill(_URL, "code-review")], _skill_reader_tool())

        await injector.transform([Message(role=Role.USER, content="hi")])

        tool.arun.assert_awaited_once()
        assert tool.arun.await_args.kwargs["stage_level"] == StageDisplayLevel.INFO

    @pytest.mark.asyncio
    async def test_the_skill_name_is_passed_to_the_tool(self):
        injector, tool = _make([_URL], [_skill(_URL, "code-review")], _skill_reader_tool())

        await injector.transform([Message(role=Role.USER, content="hi")])

        assert tool.arun.await_args.kwargs["skill_name"] == "code-review"


class TestLaterTurns:

    @pytest.mark.asyncio
    async def test_nothing_is_injected_once_the_picks_are_no_longer_this_turns(self):
        injector, tool = _make([_URL], [_skill(_URL, "code-review")], _skill_reader_tool())
        first = await injector.transform([Message(role=Role.USER, content="hi")])

        # Next turn the chip is on an earlier message, so no pick is current.
        injector, tool = _make([], [_skill(_URL, "code-review")], _skill_reader_tool())
        messages = [*first, Message(role=Role.USER, content="clarify?")]

        assert await injector.transform(messages) == messages
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_re_running_the_same_turn_does_not_duplicate_the_turn(self):
        injector, _ = _make([_URL], [_skill(_URL, "code-review")], _skill_reader_tool())
        first = await injector.transform([Message(role=Role.USER, content="hi")])

        second = await injector.transform(first)

        assert [m.role for m in second] == [m.role for m in first]

    @pytest.mark.asyncio
    async def test_re_running_the_same_turn_with_multiple_picks_does_not_duplicate(self):
        injector, _ = _make(
            [_URL, _URL2],
            [_skill(_URL, "code-review"), _skill(_URL2, "report-style")],
            _skill_reader_tool(),
        )
        first = await injector.transform([Message(role=Role.USER, content="hi")])

        second = await injector.transform(first)

        assert second == first


class TestFailedPick:

    @pytest.mark.asyncio
    async def test_an_unresolved_pick_gets_a_fixed_error_result_named_after_its_url(self):
        injector, tool = _make([_URL], tool=_skill_reader_tool())

        result = await injector.transform([Message(role=Role.USER, content="hi")])

        assert _args(result[1]) == {"skill_name": "code-review"}
        assert result[2].content == (
            "Error: the user's skill `code-review` could not be loaded."
            " The reason is shown to the user."
        )
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_missing_skill_reader_tool_injects_nothing(self):
        injector, _ = _make([_URL], [_skill(_URL, "code-review")])
        messages = [Message(role=Role.USER, content="hi")]

        assert await injector.transform(messages) == messages
