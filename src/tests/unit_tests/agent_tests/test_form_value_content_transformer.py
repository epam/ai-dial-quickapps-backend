"""``_FormValueContentTransformer`` — form_value routing depends on the form's source tool."""

from types import SimpleNamespace

import pytest
from aidial_sdk.chat_completion import Message

import quickapp.common  # noqa: F401 - init package chain before toolset imports
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.core.agent._form_value_content_transformer import _FormValueContentTransformer
from quickapp.core.agent.models import STATE_KEY_FORM_SCHEMA_SOURCE_TOOL


def _msg_with_form_value(form_value, state=None) -> Message:
    cc = {"form_value": form_value}
    if state is not None:
        cc["state"] = state
    return Message.model_validate({"role": "user", "content": "submitted", "custom_content": cc})


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
    return DeploymentToolSet.model_validate({"name": "ts", "type": "dial-deployment", "tools": [tool]})


class TestFormValueContentTransformer:

    @pytest.mark.asyncio
    async def test_injects_when_source_tool_has_no_conversation_mode(self):
        t = _FormValueContentTransformer(_config([_deployment_ts()]))
        msg = _msg_with_form_value({"a": 1}, state={STATE_KEY_FORM_SCHEMA_SOURCE_TOOL: "my_tool"})

        result = await t.transform([msg])

        assert result[0].content.startswith("submitted")
        assert "<form_value>" in result[0].content
        assert result[0].custom_content.form_value is None
        # request's own message is not mutated
        assert msg.custom_content.form_value == {"a": 1}

    @pytest.mark.asyncio
    async def test_no_injection_when_source_tool_is_resumable(self):
        t = _FormValueContentTransformer(_config([_deployment_ts({"resumable": True})]))
        msg = _msg_with_form_value({"a": 1}, state={STATE_KEY_FORM_SCHEMA_SOURCE_TOOL: "my_tool"})

        result = await t.transform([msg])

        assert result[0] is msg

    @pytest.mark.asyncio
    async def test_injects_when_source_tool_found_but_other_tool_is_resumable(self):
        # the form came from "my_tool" (no conversation_mode); another resumable tool
        # existing in the app must not block injection — it is not the form's source
        t = _FormValueContentTransformer(
            _config([_deployment_ts(), _deployment_ts({"resumable": True}, tool_name="other")])
        )
        msg = _msg_with_form_value({"a": 1}, state={STATE_KEY_FORM_SCHEMA_SOURCE_TOOL: "my_tool"})

        result = await t.transform([msg])

        assert "<form_value>" in result[0].content

    @pytest.mark.asyncio
    async def test_no_injection_without_source_marker(self):
        t = _FormValueContentTransformer(_config([_deployment_ts()]))
        msg = _msg_with_form_value({"a": 1})

        result = await t.transform([msg])

        assert result[0] is msg

    @pytest.mark.asyncio
    async def test_empty_content_gets_block_only(self):
        t = _FormValueContentTransformer(_config([_deployment_ts()]))
        msg = Message.model_validate(
            {
                "role": "user",
                "content": None,
                "custom_content": {
                    "form_value": {"a": 1},
                    "state": {STATE_KEY_FORM_SCHEMA_SOURCE_TOOL: "my_tool"},
                },
            }
        )

        result = await t.transform([msg])

        assert result[0].content.startswith("<form_value>")

    @pytest.mark.asyncio
    async def test_injects_when_conversation_mode_resumable_false(self):
        # explicit {"resumable": false} is not resumable -> inject
        t = _FormValueContentTransformer(_config([_deployment_ts({"resumable": False})]))
        msg = _msg_with_form_value({"a": 1}, state={STATE_KEY_FORM_SCHEMA_SOURCE_TOOL: "my_tool"})

        result = await t.transform([msg])

        assert "<form_value>" in result[0].content
