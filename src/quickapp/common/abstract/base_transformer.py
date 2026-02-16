from abc import ABC, abstractmethod

from aidial_sdk.chat_completion import Message


class MessagesTransformer(ABC):
    """Typed transformer that operates on a list of Messages with explicit ordering."""

    @abstractmethod
    def transform(self, messages: list[Message]) -> list[Message]: ...
