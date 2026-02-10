from injector import inject

from quickapp.common.abstract.base_transformer import MessagesTransformer


@inject
class _MessagesSetup:

    def __init__(
            self,
            transformers: list[MessagesTransformer],
    ):
        self.__transformers = transformers

    def setup(self, messages: list) -> list:
        for transformer in self.__transformers:
            messages = transformer.transform(messages)
        return messages