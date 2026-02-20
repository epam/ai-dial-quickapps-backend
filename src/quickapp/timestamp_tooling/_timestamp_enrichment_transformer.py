from zoneinfo import ZoneInfo

from aidial_sdk.chat_completion import Message, Role

from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.message_metadata import (
    USER_TIMEZONE_STATE_KEY,
    MessageMetadata,
    TimestampSource,
)


class _TimestampEnrichmentTransformer(PreInvocationTransformer):
    """Appends human-readable timestamp annotations to TOOL messages."""

    def transform(self, messages: list[Message]) -> list[Message]:
        user_tz = self._find_user_timezone(messages)

        for msg in messages:
            if msg.role != Role.TOOL:
                continue
            if not msg.custom_content or not msg.custom_content.state:
                continue

            metadata = MessageMetadata.from_state(msg.custom_content.state)
            if metadata.response_timestamp is None:
                continue

            # Skip non-text content types to avoid corrupting structured output
            if metadata.content_type is not None and not metadata.content_type.startswith("text/"):
                continue

            annotation = self._build_annotation(metadata, user_tz)
            if msg.content is None:
                msg.content = annotation
            elif isinstance(msg.content, str):
                msg.content = msg.content + annotation
            else:
                msg.content = str(msg.content) + annotation

        return messages

    @staticmethod
    def _find_user_timezone(messages: list[Message]) -> str | None:
        """Scan messages in reverse for the most recent _user_timezone setting."""
        for msg in reversed(messages):
            if msg.role != Role.TOOL:
                continue
            if not msg.custom_content or not msg.custom_content.state:
                continue
            if USER_TIMEZONE_STATE_KEY in msg.custom_content.state:
                return msg.custom_content.state[USER_TIMEZONE_STATE_KEY]
        return None

    @staticmethod
    def _build_annotation(metadata: MessageMetadata, user_tz: str | None) -> str:
        ts = metadata.response_timestamp
        if ts is None:
            return ""

        tz_name = metadata.timezone_name or "UTC"
        source = metadata.timestamp_source or TimestampSource.SERVER

        if user_tz:
            try:
                ts = ts.astimezone(ZoneInfo(user_tz))
                tz_name = user_tz
            except (KeyError, ValueError):
                pass

        if source == TimestampSource.USER_TIMEZONE:
            source_label = "user-provided timezone"
        else:
            source_label = "server default timezone"

        formatted = ts.strftime("%Y-%m-%d %H:%M:%S")
        return f"\n[Timestamp: {formatted} {tz_name} ({source_label})]"
