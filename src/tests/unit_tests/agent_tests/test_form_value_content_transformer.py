"""``_FormValueContentTransformer`` — per-message form_value injection based on the form's
source tool resolved from history before each message."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import Message

from quickapp.core.agent._form_value_content_transformer import _FormValueContentTransformer


def _msg_with_form_value(form_value) -> Message:
    return Message.model_validate(
        {"role": "user", "content": "submitted", "custom_content": {"form_value": form_value}}
    )


def _history_with_form_schema(
    tool_name="my_tool", tool_call_id="tc-1", schema=None
) -> list[Message]:
    """assistant(tool_call) + tool(result with form_schema) pair."""
    assistant = Message.model_validate(
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": "{}"},
                }
            ],
        }
    )
    tool_msg = Message.model_validate(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": "result",
            "custom_content": {"form_schema": schema or {"type": "object"}},
        }
    )
    return [assistant, tool_msg]


def _tool(name="my_tool", resumable=None, propagate_form_value_to_content=True) -> MagicMock:
    """A runtime tool stub: openai_function_name + tool_config fields."""
    from quickapp.config.tools.deployment import DialDeploymentTool

    tool = MagicMock()
    tool.openai_function_name.return_value = name
    cm = None if resumable is None else SimpleNamespace(resumable=resumable)
    tool.tool_config.conversation_mode = cm
    # _propagate_to_content checks isinstance(tool_config, DialDeploymentTool)
    tool.tool_config.__class__ = DialDeploymentTool
    tool.tool_config.propagate_form_value_to_content = propagate_form_value_to_content
    return tool


def _tools(*tools) -> list:
    return list(tools)


class TestFormValueContentTransformer:

    @pytest.mark.asyncio
    async def test_injects_when_source_tool_has_no_conversation_mode(self):
        t = _FormValueContentTransformer(_tools(_tool()))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert result[-1].content.startswith("submitted")
        assert "<form_value>" in result[-1].content
        # form_value is kept in custom_content (deployment tools read it from raw messages)
        assert result[-1].custom_content.form_value == {"a": 1}
        # request's own message is not mutated
        assert msg.custom_content.form_value == {"a": 1}

    @pytest.mark.asyncio
    async def test_no_injection_when_source_tool_is_resumable(self):
        t = _FormValueContentTransformer(_tools(_tool(resumable=True)))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert result[-1] is msg

    @pytest.mark.asyncio
    async def test_injects_when_source_tool_found_but_other_tool_is_resumable(self):
        # the form came from "my_tool" (no conversation_mode); another resumable tool
        # existing in the app must not block injection — it is not the form's source
        t = _FormValueContentTransformer(_tools(_tool(), _tool(name="other", resumable=True)))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert "<form_value>" in result[-1].content

    @pytest.mark.asyncio
    async def test_no_injection_when_no_form_schema_in_history(self):
        # source tool unknown → no tool to read propagate_form_value_to_content from → no injection
        t = _FormValueContentTransformer(_tools(_tool()))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([msg])

        assert result[0] is msg

    @pytest.mark.asyncio
    async def test_injects_into_every_message_with_form_value(self):
        # two user messages with form_value, both after the form in history:
        # both must get the block (KV-cache stability: prefix must stay deterministic)
        t = _FormValueContentTransformer(_tools(_tool()))
        msg1 = _msg_with_form_value({"a": 1})
        msg2 = _msg_with_form_value({"b": 2})

        result = await t.transform([*_history_with_form_schema(), msg1, msg2])

        assert "<form_value>" in result[-2].content
        assert "<form_value>" in result[-1].content
        assert result[-2].custom_content.form_value == {"a": 1}
        assert result[-1].custom_content.form_value == {"b": 2}

    @pytest.mark.asyncio
    async def test_per_message_source_resolution(self):
        # first form from non-resumable "my_tool", second form from resumable "new_tool";
        # the message after the first form gets injected, the one after the second does not
        t = _FormValueContentTransformer(_tools(_tool(), _tool(name="new_tool", resumable=True)))
        msg1 = _msg_with_form_value({"a": 1})
        msg2 = _msg_with_form_value({"b": 2})
        history = [
            *_history_with_form_schema(tool_name="my_tool", tool_call_id="tc-1"),
            msg1,
            *_history_with_form_schema(tool_name="new_tool", tool_call_id="tc-2"),
            msg2,
        ]

        result = await t.transform(history)

        assert "<form_value>" in result[2].content  # msg1: source my_tool, not resumable
        assert result[5] is msg2  # msg2: source new_tool, resumable → untouched

    @pytest.mark.asyncio
    async def test_form_after_message_not_counted(self):
        # form_schema appears AFTER the user message with form_value → no source before it
        # → source unknown → no injection
        t = _FormValueContentTransformer(_tools(_tool()))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([msg, *_history_with_form_schema()])

        assert result[0] is msg

    @pytest.mark.asyncio
    async def test_empty_content_gets_block_only(self):
        t = _FormValueContentTransformer(_tools(_tool()))
        msg = Message.model_validate(
            {"role": "user", "content": None, "custom_content": {"form_value": {"a": 1}}}
        )

        result = await t.transform([*_history_with_form_schema(), msg])

        assert result[-1].content.startswith("<form_value>")

    @pytest.mark.asyncio
    async def test_injects_when_conversation_mode_resumable_false(self):
        # explicit {"resumable": false} is not resumable -> inject
        t = _FormValueContentTransformer(_tools(_tool(resumable=False)))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert "<form_value>" in result[-1].content


class TestPropagateFormValueToContentFlag:
    @pytest.mark.asyncio
    async def test_no_injection_when_flag_false(self):
        t = _FormValueContentTransformer(_tools(_tool(propagate_form_value_to_content=False)))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert result[-1] is msg
        assert "<form_value>" not in (result[-1].content or "")

    @pytest.mark.asyncio
    async def test_no_injection_when_flag_unset(self):
        t = _FormValueContentTransformer(_tools(_tool(propagate_form_value_to_content=None)))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert result[-1] is msg

    @pytest.mark.asyncio
    async def test_injection_when_flag_true(self):
        t = _FormValueContentTransformer(_tools(_tool(propagate_form_value_to_content=True)))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert "<form_value>" in result[-1].content

    @pytest.mark.asyncio
    async def test_no_injection_when_source_tool_unknown(self):
        # flag true but source tool not among runtime tools → no injection
        t = _FormValueContentTransformer(_tools(_tool(name="other")))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert result[-1] is msg
