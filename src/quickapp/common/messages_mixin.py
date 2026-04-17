import logging

from aidial_sdk.chat_completion import Message
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MessagesMixin(BaseModel):
    """
    Mixin to handle message appending, extending, and access.
    """

    _messages: list[Message] | None = None

    def append_message(self, message: Message) -> None:
        if self._messages is None:
            raise RuntimeError("messages are not set")
        self._messages.append(message)
        logger.debug("Appending messages")

    def extend_messages(self, messages: list[Message]) -> None:
        if self._messages is None:
            raise RuntimeError("messages are not set")
        self._messages.extend(messages)
        logger.debug("Extending messages")

    @property
    def messages(self) -> list[Message]:
        if self._messages is None:
            raise RuntimeError("Messages are not set")
        return self._messages

    @messages.setter
    def messages(self, messages: list[Message]) -> None:
        if self._messages is not None:
            raise RuntimeError("Messages are already set")
        self._messages = messages
