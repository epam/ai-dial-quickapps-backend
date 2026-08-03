"""Hand-off of a Choice stage opened while tool-call arguments were still streaming."""

from aidial_sdk.chat_completion import Stage


class AdoptedToolStage:
    """An already-open UI stage plus the time it was first opened.

    Created during orchestrator stream consumption when tool-call argument chunks
    arrive; consumed by ``StagedBaseTool.arun`` so execution reuses the same stage
    (and total duration includes argument streaming).
    """

    __slots__ = ("stage", "start_time", "streamed_parameter_names")

    def __init__(
        self,
        stage: Stage,
        start_time: float,
        streamed_parameter_names: frozenset[str] | None = None,
    ) -> None:
        self.stage = stage
        self.start_time = start_time
        self.streamed_parameter_names = streamed_parameter_names or frozenset()
