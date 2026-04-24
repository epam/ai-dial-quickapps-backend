from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.synthetic_injection.injection_enums import (
    InjectionFrequency,
    InjectionPosition,
)
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.common.time_provider import TimeProvider
from quickapp.config.application import ApplicationConfig
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
        config_provider: ProviderOf[ApplicationConfig],
    ):
        self.__time_provider = time_provider
        self.__config_provider = config_provider

    async def get_tool_name(self) -> str:
        return CURRENT_TIMESTAMP_TOOL_NAME

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS

    async def get_position(self, messages: list[Message]) -> InjectionPosition:
        return InjectionPosition.END

    async def get_content(self, messages: list[Message]) -> str | None:
        features = self.__config_provider.get().features
        if features is None or features.timestamp is None or not messages:
            return None
        now = self.__time_provider.now()
        return self.__time_provider.format_timestamp(now)
