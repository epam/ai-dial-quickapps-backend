class FallbackAgentStopException(Exception):
    """Raised by FallbackProcessor when a `stop` fallback strategy fires.

    Propagates through the orchestrator unhandled and is caught by the completion
    handler, which converts it to a generic user-facing message via the resolver.
    """
