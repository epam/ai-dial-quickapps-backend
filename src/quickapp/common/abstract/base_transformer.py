from abc import ABC, abstractmethod

from aidial_sdk.chat_completion import Message


class MessageTransformer(ABC):
    """Base transformer that operates on a list of Messages."""

    @abstractmethod
    def transform(self, messages: list[Message]) -> list[Message]: ...


class MessagesSetupTransformer(MessageTransformer, ABC):
    """Runs once at request setup, in _MessagesSetup.setup()."""

    ...


class PreInvocationTransformer(MessageTransformer, ABC):
    """Runs every iteration, in AssistantInvoker.__prepare_messages()."""

    ...
