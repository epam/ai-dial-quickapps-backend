from datetime import datetime
from zoneinfo import ZoneInfo

from quickapp.common.message_metadata import TimestampSource


class TimeProvider:
    def __init__(self, tz: ZoneInfo, source: TimestampSource = TimestampSource.SERVER):
        self.__tz = tz
        self.__source = source

    def now(self) -> datetime:
        return datetime.now(self.__tz)

    @property
    def tz_name(self) -> str:
        return str(self.__tz)

    @property
    def source(self) -> TimestampSource:
        return self.__source
