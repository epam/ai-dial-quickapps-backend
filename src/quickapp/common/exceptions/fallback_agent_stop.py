class FallbackAgentStopException(Exception):
    """Raised by FallbackProcessor when a `stop` fallback strategy fires.

    Propagates through the orchestrator unhandled and is caught by the completion
    handler, which converts it to a generic user-facing message via the resolver.
    """

    def __init__(self, tool_call_id: str) -> None:
        super().__init__(f"Stop fallback strategy triggered for tool_call_id={tool_call_id}")
