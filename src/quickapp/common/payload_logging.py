"""The payload-debugging switch (content policy, design #434 / issue #436).

The content rule (enforced everywhere else, see ``common.lifecycle_logging``) keeps
message bodies, tool-call arguments, and response payloads out of the logs at every
level. This module is the single, deliberate exception: the one place allowed to render
payload content, and only behind the ``LOG_PAYLOADS`` opt-in, with each field truncated.

Because ``LoggingSettings`` is consumed once at startup and not kept in the DI graph
(``LoggingConfig`` applies it and discards it), the switch state lives here as module-level
config, set once by ``LoggingConfig`` via :func:`configure_payload_logging`. Callers read it
through :func:`payloads_enabled` / :func:`log_payload` without touching settings. The module
takes primitives rather than ``LoggingSettings`` so ``common`` stays free of a ``config``
import.
"""

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

_DEFAULT_MAX_LENGTH = 2000
_TRUNCATION_MARKER = "…[truncated]"

_enabled = False
_max_length = _DEFAULT_MAX_LENGTH


def configure_payload_logging(enabled: bool, max_length: int) -> None:
    """Apply the ``LOG_PAYLOADS`` / ``LOG_PAYLOADS_MAX_LENGTH`` settings.

    Called once at startup by ``LoggingConfig``. Tests may call it directly (and should
    restore the defaults afterwards).
    """
    global _enabled, _max_length
    _enabled = enabled
    _max_length = max_length


def payloads_enabled() -> bool:
    """Whether payload-bearing records may be emitted (``LOG_PAYLOADS=true``)."""
    return _enabled


def _truncate(value: Any) -> str:
    """Render ``value`` as a string capped at the configured max length.

    Longer values are cut and marked with an ellipsis so a truncated payload is never
    mistaken for the whole thing.
    """
    text = value if isinstance(value, str) else str(value)
    if len(text) <= _max_length:
        return text
    return text[:_max_length] + _TRUNCATION_MARKER


def log_payload(logger: logging.Logger, msg: str, *args: Any) -> None:
    """Emit a payload-bearing DEBUG record, but only when ``LOG_PAYLOADS`` is on.

    Each ``%s`` argument is truncated to the configured cap. A no-op (nothing is rendered
    or emitted) when the switch is off, so callers can pair it with an unconditional
    structure summary without guarding it themselves.
    """
    if not _enabled:
        return
    logger.debug(msg, *(_truncate(arg) for arg in args))


def summarize_roles(messages: Iterable[Any]) -> Counter[str]:
    """Count messages by ``role`` — a structure summary that carries no message bodies.

    Handles both message objects (``message.role``) and serialized message dicts
    (``message["role"]``); a missing role falls under ``"unknown"``. The resulting
    ``Counter`` renders as ``Counter({role: count})``.
    """

    def _role(message: Any) -> str:
        if isinstance(message, Mapping):
            return str(message.get("role") or "unknown")
        return str(getattr(message, "role", None) or "unknown")

    return Counter(_role(message) for message in messages)
