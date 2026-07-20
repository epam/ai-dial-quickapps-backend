import logging

import pytest
from pydantic import ValidationError

from quickapp.common.exceptions import ToolErrorException
from quickapp.common.exceptions.fallback_agent_stop import FallbackAgentStopException
from quickapp.common.tool_fallback.processor import FallbackProcessor
from quickapp.config.tools.tool_fallback import (
    ContinueStrategyModel,
    RetryStrategyModel,
    TriggerOn,
    TriggerOnType,
)


def test_fallback_agent_stop_exception_is_exception():
    exc = FallbackAgentStopException()
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


def test_retry_strategy_still_requires_instructions():
    with pytest.raises(ValidationError):
        RetryStrategyModel()  # type: ignore[call-arg]


# -- continue always forwards error ------------------------------------------


def test_continue_catchall_forwards_tool_error_message():
    err = ToolErrorException("my_tool", "public error detail")
    result = FallbackProcessor.process_fallback([ContinueStrategyModel()], "c", err)
    assert result.content == "public error detail"


def test_continue_catchall_forwards_plain_error_str():
    err = ValueError("connection refused")
    result = FallbackProcessor.process_fallback([ContinueStrategyModel()], "c", err)
    assert result.content == "connection refused"


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
    assert result.content == "rate limit hit\n\nWait and retry with a smaller request."


def test_continue_with_trigger_no_instructions_forwards_error_only():
    err = ToolErrorException("my_tool", "quota exceeded")
    strategies = [
        ContinueStrategyModel(
            trigger_on=TriggerOn(type=TriggerOnType.contains, value="quota"),
        ),
        ContinueStrategyModel(),
    ]
    result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == "quota exceeded"


def test_continue_catchall_ignores_instructions(caplog):
    # instructions on catch-all (no trigger_on) are deprecated and ignored
    err = ToolErrorException("my_tool", "auth failed")
    strategies = [
        ContinueStrategyModel(instructions="These instructions should be ignored."),
    ]
    with caplog.at_level(logging.WARNING, logger="quickapp.common.tool_fallback.continue_strategy"):
        result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == "auth failed"
    assert any(
        r.name == "quickapp.common.tool_fallback.continue_strategy"
        and "instructions" in r.message.lower()
        for r in caplog.records
    )


# -- retry new semantics (mirrors continue) ----------------------------------


def test_retry_catchall_forwards_error_ignores_instructions(caplog):
    # retry with no trigger_on: error forwarded, instructions ignored (new semantics)
    err = ToolErrorException("my_tool", "db connection failed")
    strategies = [RetryStrategyModel(instructions="Analyze and retry.")]
    with caplog.at_level(logging.WARNING):
        result = FallbackProcessor.process_fallback(strategies, "c", err)
    assert result.content == "db connection failed"


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
    assert result.content == "rate limit hit\n\nWait 30 seconds and retry."
