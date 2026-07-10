import pytest
from pydantic import ValidationError

from quickapp.common.exceptions import ToolErrorException, ToolTimeoutError
from quickapp.common.tool_fallback.processor import FallbackProcessor, _format_timeout_message
from quickapp.config.tools.tool_fallback import (
    ContinueStrategyModel,
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
    assert result.content == "custom tool-timeout instructions"


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


def test_stop_strategy_with_trigger_preempts():
    err = ToolTimeoutError("rag_search", 300)
    strategies = [
        StopStrategyModel(
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="timed out"),
        ),
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    # Stop strategy returns its handler's message (non-empty per handler)
    assert result.content


# -- Non-timeout path unchanged --------------------------------------------


def test_non_timeout_error_uses_default_catchall():
    err = ValueError("something else")
    result = FallbackProcessor.process_fallback(_default_strategies(), "c", err)
    # Default ContinueStrategyModel catch-all returns the generic text.
    assert "An error occurs" in result.content
    assert "timed out" not in result.content


def test_non_timeout_error_ignores_forward_tool_error_message_for_non_tool_errors():
    err = ValueError("something else")
    strategies = [ContinueStrategyModel(forward_tool_error_message=True)]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert "An error occurs" in result.content


def test_tool_error_can_forward_tool_error_message():
    err = ToolErrorException("rag_search", "public error")
    strategies = [ContinueStrategyModel(forward_tool_error_message=True)]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == "public error"


def test_tool_error_can_append_instructions_after_forwarded_error():
    err = ToolErrorException("rag_search", "public error")
    strategies = [
        ContinueStrategyModel(
            instructions="Try another applicable tool.",
            forward_tool_error_message=True,
        )
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == "public error\n\nTry another applicable tool."


def test_tool_error_retry_strategy_can_append_instructions_after_forwarded_error():
    err = ToolErrorException("rag_search", "public error")
    strategies = [
        RetryStrategyModel(
            instructions="Analyze the error and retry.",
            forward_tool_error_message=True,
        )
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == "public error\n\nAnalyze the error and retry."


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


def test_continue_strategy_bare_trigger_without_instructions_rejected():
    with pytest.raises(ValidationError):
        ContinueStrategyModel(
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="timed out"),
        )


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


def test_retry_strategy_requires_instructions_unchanged():
    with pytest.raises(ValidationError):
        RetryStrategyModel()  # type: ignore[call-arg]


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
