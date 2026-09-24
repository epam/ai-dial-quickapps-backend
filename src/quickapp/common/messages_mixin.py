import logging

from aidial_sdk.chat_completion import Message
from pydantic import BaseModel

from quickapp.common._di_types import REQUEST_MESSAGES

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

    def replace_messages(self, messages: list[Message]) -> None:
        """Overwrite the message list. Name-protected escape hatch used by
        ``_RequestContextSetup.setup_messages`` to write the transformer-chain
        output after the raw (post-``extract_tool_calls``) list has already
        been stored via the public setter. Distinct from the single-assignment
        ``messages`` setter on purpose — accidental double-writes via the
        public setter remain a loud error.
        """
        self._messages = messages


class RequestMessagesMixin(BaseModel):
    """
    Mixin holding the raw request messages, as they arrived.

    Deliberately separate from ``MessagesMixin``: the working message list is
    injected into every tool, while the raw list is only read by initializers,
    which run before ``_RequestContextSetup.setup_messages`` populates it.
    """

    _request_messages: REQUEST_MESSAGES | None = None

    @property
    def request_messages(self) -> REQUEST_MESSAGES:
        """Raw request messages, readable by initializers before
        ``setup_messages`` populates the transformed ``messages``."""
        return self._request_messages if self._request_messages is not None else []

    @request_messages.setter
    def request_messages(self, value: REQUEST_MESSAGES) -> None:
        if self._request_messages is not None:
            raise RuntimeError("Request messages are already set")
        self._request_messages = value
