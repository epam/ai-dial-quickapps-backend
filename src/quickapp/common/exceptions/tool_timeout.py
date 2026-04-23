TOOL_TIMEOUT_PHRASE = "timed out"
"""Stable substring present in every timeout-related user-facing message.

Load-bearing: `TriggerOn(type=contains, value=TOOL_TIMEOUT_PHRASE)` in tool
fallback configuration relies on this appearing in both `str(ToolTimeoutError)`
(stage UI short form) and the long LLM-facing message emitted by
`FallbackProcessor._process_timeout`.
"""


class ToolTimeoutError(RuntimeError):
    """Raised when a tool invocation exceeds its configured timeout."""

    def __init__(self, tool_name: str, timeout_seconds: float):
        super().__init__(
            f"Tool call '{tool_name}' {TOOL_TIMEOUT_PHRASE} after {timeout_seconds} seconds."
        )
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
