from abc import ABC, abstractmethod


class CompletionHookRunner(ABC):
    """Runs blocking ``on_completion`` hooks after the orchestrator loop finished normally.

    Implementations must not raise ``Exception``: a failing hook never fails the request.
    ``asyncio.CancelledError`` must propagate.
    """

    @abstractmethod
    async def run(self, *, iteration_count: int, total_tool_calls: int) -> None: ...
