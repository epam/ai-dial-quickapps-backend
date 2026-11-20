"""``_FormValueContentTransformer`` — per-message form_value injection based on the form's
source tool resolved from history before each message."""

from types import SimpleNamespace

import pytest
from aidial_sdk.chat_completion import Message

import quickapp.common  # noqa: F401 - init package chain before toolset imports
from quickapp.config.toolsets.deployment import DeploymentToolSet
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


def _config(tool_sets) -> SimpleNamespace:
    return SimpleNamespace(tool_sets=tool_sets)


def _deployment_ts(conversation_mode=None, tool_name="my_tool") -> DeploymentToolSet:
    tool = {
        "type": "deployment-tool",
        "deployment": {"deployment_id": "apps/x/dep"},
        "open_ai_tool": {
            "function": {
                "name": tool_name,
                "description": "d",
                "parameters": {"type": "object", "properties": {}},
            }
        },
    }
    if conversation_mode is not None:
        tool["conversation_mode"] = conversation_mode
    return DeploymentToolSet.model_validate(
        {"name": "ts", "type": "dial-deployment", "tools": [tool]}
    )


class TestFormValueContentTransformer:

    @pytest.mark.asyncio
    async def test_injects_when_source_tool_has_no_conversation_mode(self):
        t = _FormValueContentTransformer(_config([_deployment_ts()]))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert result[-1].content.startswith("submitted")
        assert "<form_value>" in result[-1].content
        assert result[-1].custom_content.form_value is None
        # request's own message is not mutated
        assert msg.custom_content.form_value == {"a": 1}

    @pytest.mark.asyncio
    async def test_no_injection_when_source_tool_is_resumable(self):
        t = _FormValueContentTransformer(_config([_deployment_ts({"resumable": True})]))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert result[-1] is msg

    @pytest.mark.asyncio
    async def test_injects_when_source_tool_found_but_other_tool_is_resumable(self):
        # the form came from "my_tool" (no conversation_mode); another resumable tool
        # existing in the app must not block injection — it is not the form's source
        t = _FormValueContentTransformer(
            _config([_deployment_ts(), _deployment_ts({"resumable": True}, tool_name="other")])
        )
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert "<form_value>" in result[-1].content

    @pytest.mark.asyncio
    async def test_injects_when_no_form_schema_in_history(self):
        # source tool unknown → treated as non-resumable → inject (data must not be lost)
        t = _FormValueContentTransformer(_config([_deployment_ts()]))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([msg])

        assert "<form_value>" in result[0].content

    @pytest.mark.asyncio
    async def test_injects_into_every_message_with_form_value(self):
        # two user messages with form_value, both after the form in history:
        # both must get the block (KV-cache stability: prefix must stay deterministic)
        t = _FormValueContentTransformer(_config([_deployment_ts()]))
        msg1 = _msg_with_form_value({"a": 1})
        msg2 = _msg_with_form_value({"b": 2})

        result = await t.transform([*_history_with_form_schema(), msg1, msg2])

        assert "<form_value>" in result[-2].content
        assert "<form_value>" in result[-1].content
        assert result[-2].custom_content.form_value is None
        assert result[-1].custom_content.form_value is None

    @pytest.mark.asyncio
    async def test_per_message_source_resolution(self):
        # first form from non-resumable "my_tool", second form from resumable "new_tool";
        # the message after the first form gets injected, the one after the second does not
        t = _FormValueContentTransformer(
            _config([_deployment_ts(), _deployment_ts({"resumable": True}, tool_name="new_tool")])
        )
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
        # → source unknown → inject (safe default)
        t = _FormValueContentTransformer(_config([_deployment_ts()]))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([msg, *_history_with_form_schema()])

        assert "<form_value>" in result[0].content

    @pytest.mark.asyncio
    async def test_empty_content_gets_block_only(self):
        t = _FormValueContentTransformer(_config([_deployment_ts()]))
        msg = Message.model_validate(
            {"role": "user", "content": None, "custom_content": {"form_value": {"a": 1}}}
        )

        result = await t.transform([*_history_with_form_schema(), msg])

        assert result[-1].content.startswith("<form_value>")

    @pytest.mark.asyncio
    async def test_injects_when_conversation_mode_resumable_false(self):
        # explicit {"resumable": false} is not resumable -> inject
        t = _FormValueContentTransformer(_config([_deployment_ts({"resumable": False})]))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([*_history_with_form_schema(), msg])

        assert "<form_value>" in result[-1].content
