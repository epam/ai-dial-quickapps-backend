from abc import ABC, abstractmethod
from typing import TypeVar

from aidial_sdk.chat_completion import Message

_TransformerType = TypeVar("_TransformerType", bound=type)


class MessagesTransformer(ABC):
    """Typed transformer that operates on a list of Messages with explicit ordering."""

    @abstractmethod
    def transform(self, messages: list[Message]) -> list[Message]: ...
