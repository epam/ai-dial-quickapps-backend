class SubagentToolSetResolutionError(RuntimeError):
    """Raised when a subagent's declared tool sets resolve to nothing.

    Spawning anyway would run an agent with no tools, which does not fail — it
    answers from the task text alone and sounds confident doing it. That is worse
    than an error, so this is fatal to the spawn.
    """

    def __init__(self, subagent_name: str, requested: list[str], available: list[str]) -> None:
        super().__init__(
            f"Subagent '{subagent_name}' declares tool sets {requested}, none of which exist "
            f"in this app. Available tool sets: {available or '(none)'}."
        )
        self.subagent_name = subagent_name
        self.requested = requested
        self.available = available
