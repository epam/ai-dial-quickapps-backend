from abc import ABC, abstractmethod

from quickapp.common.completion_inputs import CompletionInputs


class BaseCompletionRunner(ABC):
    """Runs one completion lifecycle in the current request scope.

    Lets feature modules (e.g. the subagent spawner) drive a run without depending on core.
    """

    @abstractmethod
    async def run(self, inputs: CompletionInputs) -> object | None:
        """Run the completion; ``None`` when the manifest could not be resolved."""
        ...
