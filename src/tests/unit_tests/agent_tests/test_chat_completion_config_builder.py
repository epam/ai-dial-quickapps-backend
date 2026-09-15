from unittest.mock import MagicMock

from aidial_sdk.chat_completion import Message, Role

from quickapp.core.agent._chat_completion_config_builder import _ChatCompletionConfigBuilder
from quickapp.core.agent.lazy_loaded_tools_holder import LazyLoadedToolsHolder
from quickapp.core.agent.models import STATE_KEY_ORCHESTRATOR as ORCH


def _make_tool_dict(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}


def _make_builder(
    tools: list[dict], lazy_holder: LazyLoadedToolsHolder
) -> _ChatCompletionConfigBuilder:
    config = MagicMock()
    config.orchestrator.deployment.parameters.model_dump.return_value = {}
    config.orchestrator.deployment.deployment_id = "orchestrator-model"
    tool_choice_holder = MagicMock()
    tool_choice_holder.consume.return_value = None
    presentation_settings = MagicMock()
    presentation_settings.show_usage_statistics = False
    return _ChatCompletionConfigBuilder(
        config=config,
        tools=tools,
        response_format=None,
        tool_choice_holder=tool_choice_holder,
        pre_invocation_transformers=[],
        presentation_settings=presentation_settings,
        forwarded_headers=None,
        lazy_loaded_tools_holder=lazy_holder,
    )


def test_build_merges_lazy_tools_after_eager_tools():
    """Discovered (lazy) tools are appended to the eager tools in the outgoing payload."""
    lazy_holder = LazyLoadedToolsHolder()
    lazy_holder.add([_make_tool_dict("discovered_tool")])
    builder = _make_builder([_make_tool_dict("eager_tool")], lazy_holder)

    payload = builder.build([Message(role=Role.USER, content="hi")])

    names = [t["function"]["name"] for t in payload["tools"]]
    assert names == ["eager_tool", "discovered_tool"]


def test_build_dedupes_lazy_tools_against_eager_names():
    """A lazy tool whose name collides with an eager tool is dropped, not duplicated."""
    lazy_holder = LazyLoadedToolsHolder()
    lazy_holder.add([_make_tool_dict("shared_name"), _make_tool_dict("discovered_tool")])
    builder = _make_builder([_make_tool_dict("shared_name")], lazy_holder)

    payload = builder.build([Message(role=Role.USER, content="hi")])

    names = [t["function"]["name"] for t in payload["tools"]]
    assert names == ["shared_name", "discovered_tool"]


def test_build_with_no_lazy_tools_returns_eager_tools_only():
    lazy_holder = LazyLoadedToolsHolder()
    builder = _make_builder([_make_tool_dict("eager_tool")], lazy_holder)

    payload = builder.build([Message(role=Role.USER, content="hi")])

    assert [t["function"]["name"] for t in payload["tools"]] == ["eager_tool"]


def test_promote_orchestrator_state_to_top_level():
    """Before the next orchestrator call, state.orchestrator (response state only) is promoted to top-level."""
    msg = {
        "role": "assistant",
        "content": "ok",
        "custom_content": {
            "state": {
                "tool_execution_history": [{"role": "assistant"}],
                ORCH: {"claude_message_content": "some content"},
            },
        },
    }
    _ChatCompletionConfigBuilder._promote_orchestrator_state_to_top_level(msg)
    state = msg["custom_content"]["state"]
    assert ORCH not in state
    assert state["tool_execution_history"] == [{"role": "assistant"}]
    assert state["claude_message_content"] == "some content"


def test_promote_orchestrator_state_no_op_no_custom_content():
    """Message without custom_content is unchanged."""
    promote = _ChatCompletionConfigBuilder._promote_orchestrator_state_to_top_level
    msg = {"role": "user", "content": "hi"}
    promote(msg)
    assert "custom_content" not in msg


def test_promote_orchestrator_state_no_op_custom_content_not_dict():
    """custom_content that is not a dict is left unchanged (no crash)."""
    promote = _ChatCompletionConfigBuilder._promote_orchestrator_state_to_top_level
    msg = {"role": "assistant", "custom_content": None}
    promote(msg)
    assert msg["custom_content"] is None

    msg2 = {"role": "assistant", "custom_content": "invalid"}
    promote(msg2)
    assert msg2["custom_content"] == "invalid"


def test_promote_orchestrator_state_no_op_no_orchestrator_key():
    """State without 'orchestrator' key is unchanged."""
    promote = _ChatCompletionConfigBuilder._promote_orchestrator_state_to_top_level
    msg = {
        "custom_content": {
            "state": {"tool_execution_history": [], "other": "x"},
        },
    }
    promote(msg)
    assert msg["custom_content"]["state"] == {"tool_execution_history": [], "other": "x"}
    assert ORCH not in msg["custom_content"]["state"]


def test_promote_orchestrator_state_orchestrator_non_dict_removes_key_only():
    """If state.orchestrator is not a dict, key is removed but state is not updated (no crash)."""
    promote = _ChatCompletionConfigBuilder._promote_orchestrator_state_to_top_level
    msg = {
        "custom_content": {
            "state": {"other": "keep", ORCH: [{"stages": "invalid"}]},
        },
    }
    promote(msg)
    state = msg["custom_content"]["state"]
    assert ORCH not in state
    assert state["other"] == "keep"
    assert "stages" not in state
