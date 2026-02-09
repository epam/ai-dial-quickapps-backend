from abc import ABC, abstractmethod
from typing import TypeVar

from aidial_sdk.chat_completion import Message


_TransformerType = TypeVar("_TransformerType", bound=type)


def ordered(value: int):
    """Class decorator to set ORDER on MessagesTransformer subclasses."""

    def decorator(cls: _TransformerType) -> _TransformerType:
        if not isinstance(value, int):
            raise TypeError("ORDER must be an integer.")
        setattr(cls, "ORDER", value)
        return cls

    return decorator


class MessagesTransformer(ABC):
    """Typed transformer that operates on a list of Messages with explicit ordering."""

    ORDER: int

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls is MessagesTransformer:
            return
        if "ORDER" not in cls.__dict__ or not isinstance(cls.__dict__["ORDER"], int):
            raise TypeError("MessagesTransformer subclasses must define integer 'ORDER'.")

    @abstractmethod
    def transform(self, messages: list[Message]) -> list[Message]: ...
