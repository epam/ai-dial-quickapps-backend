import pytest

from quickapp.common.exceptions.fallback_agent_stop import FallbackAgentStopException


def test_fallback_agent_stop_exception_is_exception():
    exc = FallbackAgentStopException()
    assert isinstance(exc, Exception)


def test_fallback_agent_stop_exception_importable_from_package():
    from quickapp.common.exceptions import FallbackAgentStopException  # noqa: F401
