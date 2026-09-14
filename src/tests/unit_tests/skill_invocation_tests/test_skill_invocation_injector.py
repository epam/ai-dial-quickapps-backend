"""``_SkillInvocationInjector`` — synthetic ``read_skill`` pairs for this turn's chips."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    build_synthetic_pair,
    make_synthetic_call_id,
)
from quickapp.skill_invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skill_invocation._skill_invocation_injector import _SkillInvocationInjector
from quickapp.skills._tool_configs import SKILL_READER_TOOL_NAME
from tests.unit_tests.common.common import make_resolved_skill as _skill


def _skill_reader_tool(content: str = "manifest") -> MagicMock:
    tool = MagicMock(spec=StagedBaseTool)
    tool.tool_config = MagicMock()
    tool.tool_config.open_ai_tool.function.name = SKILL_READER_TOOL_NAME
    tool.arun = AsyncMock(
        return_value=ToolCallResult(content=content, content_type="text/markdown")
    )
    return tool


def _make(context: _InvokedSkillsContext, tool: MagicMock | None = None):
    tools_provider = MagicMock()
    tools_provider.get.return_value = [tool] if tool is not None else []
    return _SkillInvocationInjector(context, tools_provider)


def _context(urls: list[str], resolved: list = ()) -> _InvokedSkillsContext:
    context = _InvokedSkillsContext()
    context.set_current_turn_urls(urls)
    context.set_resolved_skills(list(resolved))
    return context


class TestInjection:

    @pytest.mark.asyncio
    async def test_no_chips_this_turn_leaves_the_messages_alone(self):
        messages = [Message(role=Role.USER, content="hi")]

        assert await _make(_context([])).transform(messages) == messages

    @pytest.mark.asyncio
    async def test_a_resolved_chip_becomes_a_pair_running_the_real_tool(self):
        tool = _skill_reader_tool("the manifest")
        context = _context(["skills/b/sql-style"], [_skill("skills/b/sql-style", "sql-style")])

        result = await _make(context, tool).transform([Message(role=Role.USER, content="hi")])

        assert [m.role for m in result] == [Role.USER, Role.ASSISTANT, Role.TOOL]
        call = result[1].tool_calls[0]
        assert call.function.name == SKILL_READER_TOOL_NAME
        assert json.loads(call.function.arguments) == {"skill_name": "sql-style"}
        assert result[2].content == "the manifest"
        assert result[2].tool_call_id == call.id

    @pytest.mark.asyncio
    async def test_the_stage_level_is_left_at_its_default(self):
        tool = _skill_reader_tool()
        context = _context(["skills/b/sql-style"], [_skill("skills/b/sql-style", "sql-style")])

        await _make(context, tool).transform([Message(role=Role.USER, content="hi")])

        assert "stage_level" not in tool.arun.await_args.kwargs

    @pytest.mark.asyncio
    async def test_pairs_go_right_after_the_last_user_message(self):
        tool = _skill_reader_tool()
        context = _context(["skills/b/sql-style"], [_skill("skills/b/sql-style", "sql-style")])
        messages = [
            Message(role=Role.USER, content="first"),
            Message(role=Role.ASSISTANT, content="ok"),
            Message(role=Role.USER, content="second"),
        ]

        result = await _make(context, tool).transform(messages)

        assert [m.role for m in result] == [
            Role.USER,
            Role.ASSISTANT,
            Role.USER,
            Role.ASSISTANT,
            Role.TOOL,
        ]

    @pytest.mark.asyncio
    async def test_chips_keep_their_order(self):
        tool = _skill_reader_tool()
        context = _context(
            ["skills/b/a", "skills/b/z"],
            [_skill("skills/b/a", "a"), _skill("skills/b/z", "z")],
        )

        result = await _make(context, tool).transform([Message(role=Role.USER, content="hi")])

        names = [
            json.loads(m.tool_calls[0].function.arguments)["skill_name"]
            for m in result
            if m.role == Role.ASSISTANT
        ]
        assert names == ["a", "z"]


class TestFailedChips:

    @pytest.mark.asyncio
    async def test_an_unresolved_chip_gets_a_fixed_error_result_named_after_its_url(self):
        context = _context(["skills/b/sql-style"])

        result = await _make(context, _skill_reader_tool()).transform(
            [Message(role=Role.USER, content="hi")]
        )

        assert json.loads(result[1].tool_calls[0].function.arguments) == {"skill_name": "sql-style"}
        assert result[2].content == (
            "Error: the user's skill `sql-style` could not be loaded."
            " The reason is shown to the user."
        )

    @pytest.mark.asyncio
    async def test_a_missing_skill_reader_tool_injects_nothing(self):
        context = _context(["skills/b/sql-style"], [_skill("skills/b/sql-style", "sql-style")])
        messages = [Message(role=Role.USER, content="hi")]

        assert await _make(context).transform(messages) == messages


class TestSkipping:

    @pytest.mark.asyncio
    async def test_a_pair_already_in_history_is_not_injected_again(self):
        tool = _skill_reader_tool()
        arguments = {"skill_name": "sql-style"}
        call_id = make_synthetic_call_id(SKILL_READER_TOOL_NAME, arguments, "old manifest")
        existing = build_synthetic_pair(SKILL_READER_TOOL_NAME, call_id, arguments, "old manifest")
        messages = [Message(role=Role.USER, content="hi"), *existing]
        context = _context(["skills/b/sql-style"], [_skill("skills/b/sql-style", "sql-style")])

        result = await _make(context, tool).transform(messages)

        assert result == messages
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_two_chips_deriving_the_same_name_produce_one_pair(self):
        tool = _skill_reader_tool()
        context = _context(["skills/b/dup", "skills/other/dup"])

        result = await _make(context, tool).transform([Message(role=Role.USER, content="hi")])

        assert [m.role for m in result] == [Role.USER, Role.ASSISTANT, Role.TOOL]
