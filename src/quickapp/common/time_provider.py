from datetime import datetime
from zoneinfo import ZoneInfo

from quickapp.common.message_metadata import TimestampSource


class TimeProvider:
    """Request-scoped provider that returns the current time in a configured timezone.

    Calls ``datetime.now(tz)`` on each invocation — it is a provider, not a
    snapshot.  Each tool result gets stamped with its actual production time.
    """

    def __init__(
        self, tz: ZoneInfo = ZoneInfo("UTC"), source: TimestampSource = TimestampSource.DEFAULT
    ):
        self._tz = tz
        self._source = source

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

    def format_timestamp(self, dt: datetime) -> str:
        return f"{dt.isoformat()} ({self.tz_name}, source={self._source.value})"
