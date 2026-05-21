from quickapp.agent._chat_completion_config_builder import _ChatCompletionConfigBuilder
from quickapp.agent.models import STATE_KEY_ORCHESTRATOR as ORCH


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
