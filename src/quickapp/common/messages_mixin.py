import logging
from dataclasses import dataclass

from aidial_sdk.chat_completion import Message

logger = logging.getLogger(__name__)


@dataclass
class MessagesMixin:
    """
    Mixin to handle message appending, extending, and access.
    """

    _messages: list[Message] | None = None

    def append_message(self, message: Message) -> None:
        if not self._messages:
            raise RuntimeError("messages are not set")
        self._messages.append(message)
        logger.debug("Appending messages")

    def extend_messages(self, messages: list[Message]) -> None:
        if not self._messages:
            raise RuntimeError("messages are not set")
        self._messages.extend(messages)
        logger.debug("Extending messages")

    @property
    def messages(self) -> list[Message]:
        if not self._messages:
            raise RuntimeError("Messages are not set")
        return self._messages

    @messages.setter
    def messages(self, messages: list[Message]) -> None:
        if self._messages:
            raise RuntimeError("Messages are already set")
        self._messages = messages
