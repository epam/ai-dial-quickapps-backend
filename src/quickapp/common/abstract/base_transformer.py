from abc import ABC, abstractmethod

from aidial_sdk.chat_completion import Message


class MessagesTransformer(ABC):
    """Runs once at request setup in _MessagesSetup.setup().

    Mutates the canonical message list that persists across iterations.
    """

    @abstractmethod
    async def transform(self, messages: list[Message]) -> list[Message]: ...


class PreInvocationTransformer(ABC):
    """Runs before every LLM call in AssistantInvoker.__prepare_messages().

    Each transformer is responsible for its own deep-copy strategy — it copies
    only the messages it mutates, leaving the rest as references.  Annotations
    produced by these transformers only exist in the per-invocation copies and
    are never persisted to the canonical message history.
    """

    @abstractmethod
    def transform(self, messages: list[Message]) -> list[Message]: ...
