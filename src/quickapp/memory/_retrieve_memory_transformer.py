import logging

import httpx
from aidial_sdk.chat_completion import Message, Role
from injector import inject, ProviderOf

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.di_types import DIAL_API_KEY
from quickapp.memory._memory_models import MemoryRow, RetrieveResponse
from quickapp.memory._memory_settings import MemorySettings

logger = logging.getLogger(__name__)


class _RetrieveMemoryTransformer(MessagesTransformer):
    """
    Retrieves core memory facts from the memory service and injects them
    as a system message at the beginning of the conversation.
    """

    @inject
    def __init__(self, settings: MemorySettings, api_key_provider: ProviderOf[DIAL_API_KEY]):
        self._settings = settings
        self._api_key_provider = api_key_provider

    # TODO: make transform() async once MessagesTransformer supports async —
    #  currently _MessagesSetup.setup() is sync so we block the event loop here.
    def transform(self, messages: list[Message]) -> list[Message]:
        try:
            response = self._retrieve_memory()
        except Exception:
            logger.exception("Failed to retrieve memory from %s", self._settings.url)
            return messages

        if not response.facts:
            return messages

        memory_message = Message(
            role=Role.SYSTEM,
            content=self._format_memory(response.facts),
        )

        if messages and messages[0].role == Role.SYSTEM:
            return [messages[0], memory_message] + messages[1:]
        return [memory_message] + messages

    def _retrieve_memory(self) -> RetrieveResponse:
        with httpx.Client() as client:
            response = client.get(
                f"{self._settings.url}/memory/retrieve",
                headers={"Api-Key": self._api_key_provider.get().get_secret_value()},
            )
            response.raise_for_status()
            return RetrieveResponse.model_validate(response.json())

    @staticmethod
    def _format_memory(facts: list[MemoryRow]) -> str:
        lines = ["<core_memory>"]
        for fact in facts:
            lines.append(f"  <fact>{fact.content}</fact>")
        lines.append("</core_memory>")
        return "\n".join(lines)
