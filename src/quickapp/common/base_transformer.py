from abc import ABC, abstractmethod
from typing import Any

from aidial_sdk.chat_completion import Message


class PreTransformer(ABC):
    @abstractmethod
    def transform(self, input_param: Any): ...


class MessagesTransformer(PreTransformer):
    """Typed transformer that operates on a list of Messages."""

    @abstractmethod
    def transform(self, messages: list[Message]) -> list[Message]: ...
