"""Formatting for the INFO request-lifecycle skeleton (design #434, issue #435).

The request skeleton is written as a stable message ``prefix`` followed by
``key=value`` fields rather than free prose, so later work — JSON output (#438)
and request-scoped ids (#439) — can lift the same fields into structured
attributes without rewording the events.

Only structural metadata belongs in these records (roles, counts, sizes,
durations, names, ids, statuses); never message bodies, tool-call arguments, or
other payload content (the content rule, delivered by #436).
"""

from collections.abc import Mapping
from typing import Any


def _render(value: Any) -> str:
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{k}: {v}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple, set)):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


def format_event(prefix: str, **fields: Any) -> str:
    """Render a lifecycle event as ``"<prefix>: key=value, ..."``.

    Fields whose value is ``None`` are omitted, so callers can pass optional
    fields (e.g. token usage) unconditionally. Lists and maps render as
    structure (``[a, b]`` / ``{k: v}``) — the login result map is structure,
    not content.
    """
    parts = [f"{key}={_render(value)}" for key, value in fields.items() if value is not None]
    return f"{prefix}: {', '.join(parts)}" if parts else prefix


def format_duration(seconds: float) -> str:
    """Format an elapsed duration for a lifecycle field (e.g. ``2.10s``)."""
    return f"{seconds:.2f}s"
