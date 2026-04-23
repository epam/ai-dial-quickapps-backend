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

    def _replace_messages(self, messages: list[Message]) -> None:
        """Overwrite the message list. Name-protected escape hatch used by
        ``_RequestContextSetup.finalize_messages`` to write the transformer-
        chain output after the pre-init pass already stored the raw (post-
        ``extract_tool_calls``) list. Distinct from the single-assignment
        ``messages`` setter on purpose — accidental double-writes via the
        public setter remain a loud error.
        """
        self._messages = messages
