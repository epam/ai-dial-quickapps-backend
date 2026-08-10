"""Hand-off of a Choice stage opened while tool-call arguments were still streaming."""

from aidial_sdk.chat_completion import Stage


class AdoptedToolStage:
    """An already-open UI stage plus the time it was first opened.

    Created during orchestrator stream consumption when tool-call argument chunks
    arrive; consumed by ``StagedBaseTool.arun`` so execution reuses the same stage
    (and total duration includes argument streaming).
    """

    def __init__(
        self,
        stage: Stage,
        start_time: float,
        *,
        request_body_streamed: bool = False,
    ) -> None:
        self.stage = stage
        self.start_time = start_time
        self.request_body_streamed = request_body_streamed
