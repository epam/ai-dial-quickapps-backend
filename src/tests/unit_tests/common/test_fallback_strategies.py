import logging

import pytest
from pydantic import ValidationError

from quickapp.common.exceptions.fallback_agent_stop import FallbackAgentStopException
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
