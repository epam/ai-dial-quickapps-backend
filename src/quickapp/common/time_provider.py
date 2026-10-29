from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from quickapp.common.message_metadata import TimestampSource


class TimezoneLabel(StrEnum):
    """Whose zone the model is looking at; rendered as ``source=<label>``, never persisted."""

    USER = "user"  # from the request (X-Timezone header)
    APP_DEFAULT = "app_default"  # features.timestamp.default_timezone
    FALLBACK = "fallback"  # nothing usable given, UTC


class TimeProvider:
    """Request-scoped provider that returns the current time in a configured timezone.

    Calls ``datetime.now(tz)`` on each invocation — it is a provider, not a
    snapshot.  Each tool result gets stamped with its actual production time.
    """

    def __init__(
        self,
        tz: ZoneInfo = ZoneInfo("UTC"),
        source: TimestampSource = TimestampSource.DEFAULT,
        label: TimezoneLabel = TimezoneLabel.FALLBACK,
    ):
        self._tz = tz
        self._source = source
        self._label = label

    def now(self) -> datetime:
        return datetime.now(self._tz)

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    @property
    def tz_name(self) -> str:
        return str(self._tz)

    @property
    def source(self) -> TimestampSource:
        return self._source

    @property
    def label(self) -> TimezoneLabel:
        return self._label

    def format_timestamp(self, dt: datetime) -> str:
        tz_name = str(dt.tzinfo) if dt.tzinfo else self.tz_name
        return f"{dt.isoformat()} ({tz_name}, source={self._label.value})"
