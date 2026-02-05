import logging

from injector import inject

from quickapp.common.base_initializer import BaseInitializer
from quickapp.common.base_transformer import MessagesTransformer
from quickapp.common.messages_mixin import MessagesMixin

logger = logging.getLogger(__name__)


@inject
class _MessagePreprocessingInitializer(BaseInitializer):
    def __init__(
        self,
        messages_context: MessagesMixin,
        transformers: list[MessagesTransformer],
    ) -> None:
        self.__messages_context = messages_context
        self.__transformers = transformers

    async def initialize(self) -> None:
        messages = list(self.__messages_context.messages)
        for transformer in self.__transformers:
            messages = transformer.transform(messages)
            logger.debug(f"{type(transformer).__name__}: {{\"result\": {messages}}}")
        actual_messages = self.__messages_context.messages
        actual_messages.clear()
        actual_messages.extend(messages)
