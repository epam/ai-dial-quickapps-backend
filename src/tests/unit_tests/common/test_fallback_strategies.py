import logging

import pytest

from quickapp.common.exceptions import ToolErrorException, ToolTimeoutError
from quickapp.common.exceptions.fallback_agent_stop import FallbackAgentStopException
from quickapp.common.tool_fallback.processor import FallbackProcessor
from quickapp.config.tools.tool_fallback import (
    ContinueStrategyModel,
    RetryStrategyModel,
    StopStrategyModel,
    TriggerOn,
    TriggerOnType,
)


def test_fallback_agent_stop_exception_is_exception():
    exc = FallbackAgentStopException(tool_call_id="call_1")
    assert isinstance(exc, Exception)


def test_fallback_agent_stop_exception_importable_from_package():
    from quickapp.common.exceptions import FallbackAgentStopException  # noqa: F401

    assert issubclass(FallbackAgentStopException, Exception)


# -- Validator removal -------------------------------------------------------


def test_continue_trigger_without_instructions_no_longer_raises():
    cs = ContinueStrategyModel(trigger_on=TriggerOn(type=TriggerOnType.contains, value="timeout"))
    assert cs.trigger_on is not None
    assert cs.instructions is None


# -- forward_tool_error_message deprecation ----------------------------------


def test_forward_tool_error_message_false_still_parses():
    cs = ContinueStrategyModel(forward_tool_error_message=False)
    assert cs.forward_tool_error_message is False


def test_forward_tool_error_message_true_parses_and_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="quickapp.config.tools.tool_fallback"):
        cs = ContinueStrategyModel(forward_tool_error_message=True)
    assert cs.forward_tool_error_message is True
    assert any("forward_tool_error_message" in r.message for r in caplog.records)


# -- RetryStrategyModel deprecation ------------------------------------------


def test_retry_strategy_still_parses(caplog):
    with caplog.at_level(logging.WARNING, logger="quickapp.config.tools.tool_fallback"):
        rs = RetryStrategyModel(instructions="retry please")
    assert rs.type == "retry"
    assert rs.instructions == "retry please"
    assert any(
        "retry" in r.message.lower() and "deprecated" in r.message.lower() for r in caplog.records
    )


def test_retry_strategy_has_default_instructions(caplog):
    with caplog.at_level(logging.WARNING, logger="quickapp.config.tools.tool_fallback"):
        rs = RetryStrategyModel()
    assert rs.instructions
    assert "retry" in rs.instructions.lower()


# -- continue always forwards error ------------------------------------------


def test_continue_catchall_forwards_tool_error_message():
    err = ToolErrorException("my_tool", "public error detail")
    result = FallbackProcessor.process_fallback([ContinueStrategyModel()], "c", err)
    assert result.content == "The tool call failed with an error: public error detail"


def test_continue_catchall_forwards_plain_error_str():
    err = ValueError("connection refused")
    result = FallbackProcessor.process_fallback([ContinueStrategyModel()], "c", err)
    assert result.content == "The tool call failed with an error: connection refused"


def test_continue_with_trigger_appends_instructions_after_error():
    err = ToolErrorException("my_tool", "rate limit hit")
    strategies = [
        ContinueStrategyModel(
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="rate limit"),
            instructions="Wait and retry with a smaller request.",
        ),
        ContinueStrategyModel(),
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == (
        "The tool call failed with an error: rate limit hit\n\nWait and retry with a smaller request."
    )


def test_continue_with_trigger_no_instructions_forwards_error_only():
    err = ToolErrorException("my_tool", "quota exceeded")
    strategies = [
        ContinueStrategyModel(
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="quota"),
        ),
        ContinueStrategyModel(),
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == "The tool call failed with an error: quota exceeded"


def test_continue_catchall_with_instructions_appends_them():
    err = ToolErrorException("my_tool", "auth failed")
    strategies = [
        ContinueStrategyModel(instructions="Check credentials and retry."),
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == (
        "The tool call failed with an error: auth failed\n\nCheck credentials and retry."
    )


# -- retry semantics ---------------------------------------------------------


def test_retry_catchall_includes_instructions():
    err = ToolErrorException("my_tool", "db connection failed")
    result = FallbackProcessor.process_fallback(
        [RetryStrategyModel(instructions="Analyze and retry.")], "c", err
    )
    assert result.content == (
        "The tool call failed with an error: db connection failed\n\nAnalyze and retry."
    )


def test_retry_catchall_uses_default_instructions(caplog):
    err = ToolErrorException("my_tool", "db connection failed")
    with caplog.at_level(logging.WARNING, logger="quickapp.config.tools.tool_fallback"):
        result = FallbackProcessor.process_fallback([RetryStrategyModel()], "c", err)
    assert "db connection failed" in result.content
    assert "retry" in result.content.lower()


def test_retry_with_trigger_appends_instructions():
    err = ToolErrorException("my_tool", "rate limit hit")
    strategies = [
        RetryStrategyModel(
            instructions="Wait 30 seconds and retry.",
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="rate limit"),
        ),
        ContinueStrategyModel(),
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == (
        "The tool call failed with an error: rate limit hit\n\nWait 30 seconds and retry."
    )


# -- stop raises FallbackAgentStopException ----------------------------------


def test_stop_catchall_raises_fallback_stop_exception():
    err = ValueError("tool failed badly")
    with pytest.raises(FallbackAgentStopException):
        FallbackProcessor.process_fallback([StopStrategyModel()], "c", err)


def test_stop_with_matching_trigger_raises():
    err = ToolErrorException("my_tool", "quota exceeded for this billing period")
    strategies = [
        StopStrategyModel(trigger_on=TriggerOn(type=TriggerOnType.contains, value="quota")),
        ContinueStrategyModel(),
    ]
    with pytest.raises(FallbackAgentStopException):
        FallbackProcessor.process_fallback(strategies, "c", err)


def test_stop_with_non_matching_trigger_falls_through_to_continue():
    err = ToolErrorException("my_tool", "transient network error")
    strategies = [
        StopStrategyModel(trigger_on=TriggerOn(type=TriggerOnType.contains, value="quota")),
        ContinueStrategyModel(),
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == "The tool call failed with an error: transient network error"


def test_stop_with_timeout_raises_when_trigger_matches():
    err = ToolTimeoutError("rag_search", 300)
    strategies = [
        StopStrategyModel(trigger_on=TriggerOn(type=TriggerOnType.contains, value="timed out")),
    ]
    with pytest.raises(FallbackAgentStopException):
        FallbackProcessor.process_fallback(strategies, "c", err)
