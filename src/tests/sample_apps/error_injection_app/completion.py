"""The error-injection ``ChatCompletion`` implementation.

Two error-delivery shapes are reproduced here (verified against aidial-sdk 0.32.0):

* **Pre-stream error** -- raising an ``HTTPException`` *before* any chunk is emitted.
  The SDK turns the first (and only) queued chunk into a non-200 JSON error response
  ``{"error": {...}}``. The HTTP status is the exception's ``status_code``.
* **Mid-stream error** -- raising *after* a choice has been opened and content appended
  (see ``_stream_then_fail``). The HTTP response is already committed as
  ``200 text/event-stream``, so the SDK serializes the exception as an SSE
  ``data: {"error": ...}`` chunk appended to the live stream. DIAL Chat surfaces only
  ``display_message`` on this path.
"""

import asyncio
import logging

from aidial_sdk import HTTPException
from aidial_sdk.chat_completion import (
    ChatCompletion,
    MessageContentTextPart,
    Request,
    Response,
    Role,
)
from scenarios import (
    HAPPY_ANSWER,
    PARTIAL_CONTENT,
    SLOW_SCENARIO_DELAY_SECONDS,
    Scenario,
    ScenarioKind,
    build_help_text,
    match_scenario,
)

logger = logging.getLogger(__name__)


def _extract_last_user_text(request: Request) -> str:
    """Return the text of the last user message (string or joined text parts)."""
    for message in reversed(request.messages):
        if message.role is not Role.USER:
            continue
        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [p.text for p in content if isinstance(p, MessageContentTextPart)]
            return " ".join(parts)
    return ""


def _build_dial_exception(scenario: Scenario) -> HTTPException:
    """Build the aidial-sdk ``HTTPException`` described by an error scenario.

    Uses ``HTTPException`` directly (rather than the typed subclasses in
    ``aidial_sdk.exceptions``) so the whole matrix -- status_code, code, type,
    display_message -- stays declaratively driven by the registry.
    """
    return HTTPException(
        message=scenario.message or f"Injected error: {scenario.title}",
        status_code=scenario.status_code or 500,
        type=scenario.error_type or "runtime_error",
        code=scenario.code,
        display_message=scenario.display_message,
    )


class ErrorInjectionModel(ChatCompletion):
    """A DIAL chat-completion deployment that deterministically injects errors."""

    async def chat_completion(self, request: Request, response: Response) -> None:
        user_text = _extract_last_user_text(request)
        scenario = match_scenario(user_text)

        if scenario is None:
            logger.info("No scenario matched %r; streaming help text.", user_text)
            await self._stream_help(response)
            return

        logger.info("Matched scenario trigger=%r kind=%s", scenario.trigger, scenario.kind.value)
        await self._run_scenario(scenario, response)

    async def _run_scenario(self, scenario: Scenario, response: Response) -> None:
        kind = scenario.kind
        if kind is ScenarioKind.HAPPY:
            await self._stream_text(response, HAPPY_ANSWER)
        elif kind is ScenarioKind.PRE_STREAM_ERROR:
            # Raised before any chunk is queued -> non-200 JSON error response.
            raise _build_dial_exception(scenario)
        elif kind is ScenarioKind.MID_STREAM_ERROR:
            await self._stream_then_fail(scenario, response)
        elif kind is ScenarioKind.UNCAUGHT_EXCEPTION:
            # Non-DIAL exception -> SDK wraps it as a generic RuntimeServerError (500).
            raise RuntimeError("boom")
        elif kind is ScenarioKind.SLOW:
            await self._stream_slow(response)
        else:  # pragma: no cover - defensive, all kinds handled above
            logger.warning("Unhandled scenario kind %s; streaming help.", kind)
            await self._stream_help(response)

    async def _stream_text(self, response: Response, text: str) -> None:
        with response.create_single_choice() as choice:
            choice.append_content(text)

    async def _stream_help(self, response: Response) -> None:
        await self._stream_text(response, build_help_text())

    async def _stream_then_fail(self, scenario: Scenario, response: Response) -> None:
        # Open the choice and append content first so the HTTP 200 stream is committed;
        # the choice is intentionally left open (not closed) to model an interrupted
        # stream. Raising now yields an SSE error chunk after the visible content.
        choice = response.create_single_choice()
        choice.open()
        choice.append_content(scenario.partial_content or PARTIAL_CONTENT)
        raise _build_dial_exception(scenario)

    async def _stream_slow(self, response: Response) -> None:
        with response.create_single_choice() as choice:
            choice.append_content("Starting a deliberately slow response... ")
            await asyncio.sleep(SLOW_SCENARIO_DELAY_SECONDS)
            choice.append_content("done.")
