import copy

from aidial_sdk.chat_completion import Message, Role

from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.message_metadata import get_metadata_from_state
from quickapp.timestamp_tooling._tool_configs import SYNTHETIC_TIMESTAMP_CALL_PREFIX


class _TimestampAnnotationTransformer(PreInvocationTransformer):
    """Annotates tool messages with human-readable timestamps before each LLM
    call.

    Reads ``_message_metadata`` from ``custom_content.state`` and appends a
    ``[Timestamp: ...]`` line to the message content.  Skips synthetic
    timestamp messages (identified by the call-ID prefix) to avoid
    double-annotating.

    Uses selective deep copies — only messages that are mutated are copied.
    """

    def transform(self, messages: list[Message]) -> list[Message]:
        result: list[Message] = []
        for msg in messages:
            if msg.role == Role.TOOL and msg.tool_call_id:
                if msg.tool_call_id.startswith(SYNTHETIC_TIMESTAMP_CALL_PREFIX):
                    result.append(msg)
                    continue

                state = msg.custom_content.state if msg.custom_content else None
                metadata = get_metadata_from_state(state)
                if metadata and metadata.timestamp and metadata.timestamp.response_timestamp:
                    ts = metadata.timestamp
                    annotation = (
                        f"\n[Timestamp: {ts.response_timestamp.strftime('%Y-%m-%d %H:%M:%S')}"  # type: ignore[union-attr]
                        f" {ts.timezone_name or 'UTC'}]"
                    )
                    if not isinstance(msg.content, str):
                        result.append(msg)
                        continue
                    msg = copy.deepcopy(msg)
                    msg.content = str(msg.content or "") + annotation
            result.append(msg)
        return result
