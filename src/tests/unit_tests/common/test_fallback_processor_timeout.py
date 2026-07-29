import logging

import pytest

from quickapp.common.exceptions import (
    FallbackAgentStopException,
    ToolErrorException,
    ToolTimeoutError,
)
from quickapp.common.tool_fallback.processor import FallbackProcessor, _format_timeout_message
from quickapp.config.tools.tool_fallback import (
    ContinueStrategyModel,
    HardStopStrategyModel,
    RetryStrategyModel,
    StopStrategyModel,
    ToolFallbackConfig,
    TriggerOn,
    TriggerOnType,
)


def _default_strategies():
    return ToolFallbackConfig().strategies


# -- Timeout branch --------------------------------------------------------


def test_default_catch_all_skipped_for_timeout_returns_builtin():
    err = ToolTimeoutError("rag_search", 300)
    result = FallbackProcessor.process_fallback(_default_strategies(), "call-1", err)
    assert result.tool_call_id == "call-1"
    assert "rag_search" in result.content
    assert "300" in result.content
    assert "timed out" in result.content


def test_builtin_message_includes_numeric_timeout():
    err = ToolTimeoutError("rag_search", 42)
    result = FallbackProcessor.process_fallback([ContinueStrategyModel()], "c", err)
    assert "42" in result.content
    assert "rag_search" in result.content


def test_explicit_trigger_continue_preempts_builtin():
    err = ToolTimeoutError("rag_search", 300)
    strategies = [
        ContinueStrategyModel(
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="timed out"),
            instructions="custom tool-timeout instructions",
        ),
        ContinueStrategyModel(),  # implicit catch-all, should be skipped
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    # trigger matched: error forwarded + instructions appended
    assert "timed out" in result.content
    assert "custom tool-timeout instructions" in result.content


def test_non_matching_trigger_falls_through_to_builtin():
    err = ToolTimeoutError("rag_search", 300)
    strategies = [
        ContinueStrategyModel(
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="totally different"),
            instructions="should not apply",
        ),
        ContinueStrategyModel(),
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert "timed out" in result.content
    assert "should not apply" not in result.content


def test_customised_catch_all_is_skipped_for_timeout():
    err = ToolTimeoutError("rag_search", 300)
    strategies = [
        ContinueStrategyModel(instructions="customised-catch-all"),
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert "timed out" in result.content
    assert "customised-catch-all" not in result.content


def test_hard_stop_strategy_with_trigger_preempts_by_raising():
    err = ToolTimeoutError("rag_search", 300)
    strategies = [
        HardStopStrategyModel(
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="timed out"),
        ),
    ]
    with pytest.raises(FallbackAgentStopException):
        FallbackProcessor.process_fallback(strategies, "c", err)


def test_stop_strategy_deprecated_with_trigger_returns_content(caplog):
    err = ToolTimeoutError("rag_search", 300)
    with caplog.at_level(logging.WARNING, logger="quickapp.config.tools.tool_fallback"):
        strategies = [
            StopStrategyModel(
                trigger_on=TriggerOn(type=TriggerOnType.contains, value="timed out"),
            ),
        ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert "STOP" in result.content


# -- Non-timeout path unchanged --------------------------------------------


def test_non_timeout_error_uses_default_catchall():
    err = ValueError("something else")
    result = FallbackProcessor.process_fallback(_default_strategies(), "c", err)
    assert "something else" in result.content
    assert "timed out" not in result.content


def test_non_timeout_error_forwards_error_regardless_of_deprecated_flag():
    err = ValueError("something else")
    strategies = [ContinueStrategyModel(forward_tool_error_message=True)]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert "something else" in result.content


def test_tool_error_always_forwarded_without_explicit_flag():
    err = ToolErrorException("rag_search", "public error")
    strategies = [ContinueStrategyModel()]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == "The tool call failed with an error: public error"


def test_continue_catchall_with_instructions_included():
    err = ToolErrorException("rag_search", "public error")
    strategies = [
        ContinueStrategyModel(
            instructions="Try another applicable tool.",
            forward_tool_error_message=True,
        )
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert "public error" in result.content
    assert "Try another applicable tool." in result.content


def test_retry_catchall_includes_instructions():
    err = ToolErrorException("rag_search", "public error")
    strategies = [
        RetryStrategyModel(
            instructions="Analyze the error and retry.",
            forward_tool_error_message=True,
        )
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert "public error" in result.content
    assert "Analyze the error and retry." in result.content


def test_non_timeout_no_matching_strategy_reraises():
    err = ValueError("x")
    strategies = [
        ContinueStrategyModel(
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="no-match"),
            instructions="won't apply",
        ),
    ]
    with pytest.raises(ValueError):
        FallbackProcessor.process_fallback(strategies, "c", err)


# -- ContinueStrategyModel validator ---------------------------------------


def test_continue_strategy_trigger_without_instructions_now_valid():
    # Validator removed — trigger_on without instructions is now valid (error always forwarded)
    cs = ContinueStrategyModel(
        trigger_on=TriggerOn(type=TriggerOnType.contains, value="timed out"),
    )
    assert cs.trigger_on is not None
    assert cs.instructions is None


def test_continue_strategy_trigger_with_instructions_ok():
    cs = ContinueStrategyModel(
        trigger_on=TriggerOn(type=TriggerOnType.contains, value="timed out"),
        instructions="ok",
    )
    assert cs.instructions == "ok"


def test_continue_strategy_trigger_with_forward_tool_error_message_ok():
    cs = ContinueStrategyModel(
        trigger_on=TriggerOn(type=TriggerOnType.contains, value="timed out"),
        forward_tool_error_message=True,
    )
    assert cs.forward_tool_error_message is True


def test_continue_strategy_no_trigger_no_instructions_ok():
    # Implicit catch-all with no instructions — still valid.
    ContinueStrategyModel()


# -- Message formatter -----------------------------------------------------


def test_format_timeout_message_includes_tool_and_seconds():
    msg = _format_timeout_message(ToolTimeoutError("my_tool", 42))
    assert "my_tool" in msg
    assert "42" in msg
    assert "timed out" in msg


def test_format_timeout_message_includes_timeout_value():
    msg = _format_timeout_message(ToolTimeoutError("my_tool", 120))
    assert "my_tool" in msg
    assert "120" in msg
    assert "timed out" in msg
