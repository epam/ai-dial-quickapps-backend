"""Scenario registry for the error-injection sample model.

Each scenario maps a trigger phrase -- matched case-insensitively as a substring of the
last user message -- to one specific failure mode. The registry (``SCENARIOS``) is a
flat, ordered list; extend it by appending a new ``Scenario`` (and a matching
conversation starter in ``sample_quickapp_config.json``).
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict

# Delay (seconds) for the "slow response" scenario. Module constant on purpose: bump it
# to comfortably exceed your client's read timeout when exercising timeout behaviour.
SLOW_SCENARIO_DELAY_SECONDS: float = 30.0

# Content streamed before a mid-stream failure, so the tester sees partial output first.
PARTIAL_CONTENT = (
    "Here is the beginning of my answer, streaming normally so far. "
    "The stream is about to fail... "
)

# Short control answer for the happy path.
HAPPY_ANSWER = (
    "This is the error-injection model. Everything is working: this is a normal, "
    "successful streamed answer with no error."
)


class ScenarioKind(str, Enum):
    """How a scenario produces its behaviour."""

    HAPPY = "happy"
    PRE_STREAM_ERROR = "pre_stream_error"
    MID_STREAM_ERROR = "mid_stream_error"
    UNCAUGHT_EXCEPTION = "uncaught_exception"
    SLOW = "slow"


class Scenario(BaseModel):
    """Declarative description of one failure-mode scenario."""

    model_config = ConfigDict(frozen=True)

    trigger: str  # lowercase keyword matched as a substring of the user message
    title: str  # short human label (help text + docs)
    expected: str  # what the tester should observe in DIAL Chat
    kind: ScenarioKind
    status_code: int | None = None  # HTTP status for error kinds
    code: str | None = None  # DIAL error ``code`` (e.g. "content_filter")
    error_type: str | None = None  # DIAL error ``type``
    message: str | None = None  # internal message (logged, not shown to the user)
    display_message: str | None = None  # user-safe text; the only field DIAL Chat shows
    partial_content: str | None = None  # text streamed before a mid-stream failure


# --- Scenario registry -------------------------------------------------------------
# One entry per trigger phrase. Conversation starters in ``sample_quickapp_config.json``
# send these ``trigger`` phrases verbatim.
SCENARIOS: list[Scenario] = [
    Scenario(
        trigger="happy path",
        title="Happy path",
        expected="A normal streamed answer, HTTP 200, no error.",
        kind=ScenarioKind.HAPPY,
    ),
    Scenario(
        trigger="pre-stream 500",
        title="Pre-stream 500 with display_message",
        expected=(
            "Non-200 (500) JSON error before any content; DIAL Chat shows the "
            "display_message verbatim."
        ),
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=500,
        message="Injected pre-stream 500 from the error-injection model.",
        display_message="The upstream provider is temporarily unavailable.",
    ),
    Scenario(
        trigger="content filter",
        title="Content filter",
        expected="Non-200 (400), code=content_filter; resolver -> content-policy message.",
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=400,
        code="content_filter",
        error_type="invalid_request_error",
        message="Injected content_filter error.",
    ),
    Scenario(
        trigger="context length exceeded",
        title="Context length exceeded",
        expected="Non-200 (400), code=context_length_exceeded; resolver -> shorten-messages message.",
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=400,
        code="context_length_exceeded",
        error_type="invalid_request_error",
        message="Injected context_length_exceeded error.",
    ),
    Scenario(
        trigger="rate limit",
        title="Rate limit (429)",
        expected="Non-200 (429); resolver -> rate-limited message with 'Please try again later.'",
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=429,
        message="Injected rate-limit error.",
        display_message="Too many requests right now. Please slow down.",
    ),
    Scenario(
        trigger="auth failed",
        title="Authentication failed (401)",
        expected="Non-200 (401); resolver -> authentication-failed message.",
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=401,
        message="Injected authentication error.",
    ),
    Scenario(
        trigger="permission denied",
        title="Permission denied (403)",
        expected="Non-200 (403); resolver -> no-permission message.",
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=403,
        message="Injected permission-denied error.",
    ),
    Scenario(
        trigger="not found",
        title="Not found (404)",
        expected="Non-200 (404); resolver -> model-not-found message.",
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=404,
        message="Injected not-found error.",
    ),
    Scenario(
        trigger="payload too large",
        title="Payload too large (413)",
        expected="Non-200 (413); resolver -> payload-too-large message.",
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=413,
        message="Injected payload-too-large error.",
    ),
    Scenario(
        trigger="invalid request",
        title="Invalid request (422)",
        expected="Non-200 (422); resolver -> invalid-request message.",
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=422,
        error_type="invalid_request_error",
        message="Injected invalid-request error.",
    ),
    Scenario(
        trigger="internal error",
        title="Internal error, no display_message (500)",
        expected="Non-200 (500), no display_message; resolver -> generic internal-error message.",
        kind=ScenarioKind.PRE_STREAM_ERROR,
        status_code=500,
        message="Injected internal error without a display_message.",
    ),
    Scenario(
        trigger="mid-stream error",
        title="Mid-stream error after partial content",
        expected=(
            "HTTP 200 stream with visible partial content, then an SSE error chunk; "
            "DIAL Chat shows the display_message."
        ),
        kind=ScenarioKind.MID_STREAM_ERROR,
        status_code=500,
        message="Injected mid-stream failure.",
        display_message="The model failed while responding.",
        partial_content=PARTIAL_CONTENT,
    ),
    Scenario(
        trigger="stream failure",
        title="Mid-stream stream failure, no display_message",
        expected=(
            "HTTP 200 stream with visible partial content, then an SSE error chunk with "
            "no display_message; resolver -> generic stream-failure message."
        ),
        kind=ScenarioKind.MID_STREAM_ERROR,
        status_code=500,
        message="Injected mid-stream stream failure without a display_message.",
        partial_content=PARTIAL_CONTENT,
    ),
    Scenario(
        trigger="uncaught exception",
        title="Uncaught (non-DIAL) exception",
        expected=(
            "A plain RuntimeError; the SDK wraps it as a generic 500 (pre-stream, " "non-200)."
        ),
        kind=ScenarioKind.UNCAUGHT_EXCEPTION,
    ),
    Scenario(
        trigger="slow response",
        title="Slow response / timeout",
        expected=(
            f"Streams a token, waits {SLOW_SCENARIO_DELAY_SECONDS:.0f}s, then finishes; "
            "use it to exercise client-timeout behaviour."
        ),
        kind=ScenarioKind.SLOW,
    ),
]


def match_scenario(user_text: str) -> Scenario | None:
    """Match the message against the registry, preferring the longest trigger.

    Longest-first tie-breaking keeps overlapping phrases unambiguous (e.g. a message
    containing "mid-stream error" is not shadowed by a shorter trigger).
    """
    text = user_text.lower()
    for scenario in sorted(SCENARIOS, key=lambda s: len(s.trigger), reverse=True):
        if scenario.trigger in text:
            return scenario
    return None


def build_help_text() -> str:
    lines = [
        "Error-injection model. Send one of these phrases (or click a conversation "
        "starter) to trigger a scenario:",
        "",
    ]
    for scenario in SCENARIOS:
        lines.append(f'- "{scenario.trigger}" -> {scenario.title}: {scenario.expected}')
    return "\n".join(lines)
