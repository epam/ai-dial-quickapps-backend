import uuid

from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall
from injector import ProviderOf, inject

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.time_provider import TimeProvider
from quickapp.config.application import ApplicationConfig
from quickapp.timestamp_tooling._tool_configs import (
    CURRENT_TIMESTAMP_TOOL_NAME,
    SYNTHETIC_TIMESTAMP_CALL_PREFIX,
)


class _TimestampInjectionTransformer(MessagesTransformer):
    """Appends a synthetic tool-call + tool-result pair with the current
    timestamp at the end of the message list.

    Runs once at request setup via ``_MessagesSetup``.  Historical timestamps
    are restored from state by ``extract_tool_calls()`` with their original
    times; this transformer only appends the *current* turn's timestamp.
    """

    @inject
    def __init__(
        self,
        time_provider: TimeProvider,
        config_provider: ProviderOf[ApplicationConfig],
    ):
        self.__time_provider = time_provider
        self.__config_provider = config_provider

    def transform(self, messages: list[Message]) -> list[Message]:
        if self.__config_provider.get().features.timestamp is None or not messages:
            return messages

        now = self.__time_provider.now()
        content = self.__time_provider.format_timestamp(now)
        call_id = f"{SYNTHETIC_TIMESTAMP_CALL_PREFIX}{uuid.uuid4().hex[:12]}"

        assistant_msg = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id=call_id,
                    type="function",
                    function=FunctionCall(
                        name=CURRENT_TIMESTAMP_TOOL_NAME,
                        arguments="{}",
                    ),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content=content,
            tool_call_id=call_id,
        )

        return messages + [assistant_msg, tool_msg]
