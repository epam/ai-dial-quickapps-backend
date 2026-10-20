from contextvars import ContextVar, Token

from quickapp.common.perf_timer.perf_timer import PerformanceTimer

_current_tool_period: ContextVar[tuple[PerformanceTimer, str] | None] = ContextVar(
    "current_tool_period", default=None
)


def bind_tool_period(perf_timer: PerformanceTimer, period_key: str) -> Token:
    """Make ``period_key`` the target of ``mark_tool_milestone`` in the current async context."""
    return _current_tool_period.set((perf_timer, period_key))


def unbind_tool_period(token: Token) -> None:
    _current_tool_period.reset(token)


def mark_tool_milestone(name: str) -> None:
    """Add a milestone to the running tool's period; no-op outside a tool call."""
    current = _current_tool_period.get()
    if current is not None:
        perf_timer, period_key = current
        perf_timer.add_milestone(period_key, name)
