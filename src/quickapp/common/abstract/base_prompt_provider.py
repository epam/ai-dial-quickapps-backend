from abc import ABC, abstractmethod


class PromptPartProvider(ABC):
    """Base class for providing parts of the system prompt.

    Implementations should return their portion of the prompt text.
    Multiple providers can be composed to build the complete system prompt.
    """

    @abstractmethod
    async def get_prompt_part(self) -> str:
        """Return the prompt part provided by this provider.

        Returns:
            str: The prompt text fragment. Can be empty string if no content needed.
        """
        ...
