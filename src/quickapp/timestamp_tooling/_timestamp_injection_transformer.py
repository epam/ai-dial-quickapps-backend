from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.common.time_provider import TimeProvider
from quickapp.timestamp_tooling._tool_configs import (
    CURRENT_TIMESTAMP_TOOL_NAME,
    SYNTHETIC_TIMESTAMP_CALL_PREFIX,
)


class _TimestampInjectionTransformer(SyntheticToolCallInjector):
    """Appends a synthetic tool-call + tool-result pair with the current
    timestamp at the end of the message list on every request turn."""

    call_id_prefix = SYNTHETIC_TIMESTAMP_CALL_PREFIX

    @inject
    def __init__(
        self,
        time_provider: TimeProvider,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ):
        super().__init__(enrichers_provider)
        self.__time_provider = time_provider

    async def get_tool_name(self) -> str:
        return CURRENT_TIMESTAMP_TOOL_NAME

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS

    async def get_content(self, messages: list[Message]) -> str | None:
        if not messages:
            return None
        now = self.__time_provider.now()
        return self.__time_provider.format_timestamp(now)
