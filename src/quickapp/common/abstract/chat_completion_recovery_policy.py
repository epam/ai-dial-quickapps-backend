from abc import ABC, abstractmethod

from aidial_sdk.chat_completion.request import Message


class ChatCompletionRecoveryPolicy(ABC):
    """Attempts message recovery after a failed chat completion call."""

    @abstractmethod
    def try_recover(self, messages: list[Message], error: Exception) -> bool: ...
