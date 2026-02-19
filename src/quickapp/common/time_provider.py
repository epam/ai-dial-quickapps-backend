from datetime import datetime
from zoneinfo import ZoneInfo

from injector import inject


@inject
class TimeProvider:
    def __init__(self, tz: ZoneInfo):
        self.__tz = tz

    def now(self) -> datetime:
        return datetime.now(self.__tz)
