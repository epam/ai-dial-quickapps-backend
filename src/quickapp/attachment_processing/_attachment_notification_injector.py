import json
import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.attachment_processing._context_entries import (
    AvailableContextToolResponse,
    build_context_entries,
    extract_seen_entries_from_messages,
    should_activate_context_tool,
)
from quickapp.attachment_processing._tool_configs import AVAILABLE_CONTEXT_TOOL_NAME
from quickapp.common.synthetic_injection.injection_enums import (
    InjectionFrequency,
    InjectionPosition,
)
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)


class _AttachmentNotificationInjector(SyntheticToolCallInjector):
    """Injects synthetic tool call/result messages to inform the agent about
    available contexts when changes are detected."""

    @inject
    def __init__(self, config_provider: ProviderOf[ApplicationConfig]):
        self.__config_provider: ProviderOf[ApplicationConfig] = config_provider

    async def get_tool_name(self) -> str:
        return AVAILABLE_CONTEXT_TOOL_NAME

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS

    async def get_position(self, messages: list[Message]) -> InjectionPosition:
        return InjectionPosition.END

    async def get_content(self, messages: list[Message]) -> str | None:
        contexts = list(self.__config_provider.get().contexts)
        if not should_activate_context_tool(contexts, messages):
            return None

        seen_entries = extract_seen_entries_from_messages(messages)
        current_urls, entries = build_context_entries(contexts, seen_entries)

        if current_urls == set(seen_entries) and not any(e.status for e in entries):
            return None

        tool_response = AvailableContextToolResponse(entries=entries)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Injecting synthetic context notification with %d entries",
                len(entries),
            )

        return json.dumps(tool_response.model_dump(exclude_none=True), ensure_ascii=False)
