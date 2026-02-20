from zoneinfo import ZoneInfo

from quickapp.common.message_metadata import TimestampSource
from quickapp.common.time_provider import TimeProvider


def test_now_returns_utc():
    provider = TimeProvider(tz=ZoneInfo("UTC"))
    result = provider.now()
    assert result.tzinfo is not None
    assert str(result.tzinfo) == "UTC"


def test_now_returns_correct_offset_for_timezone():
    provider = TimeProvider(tz=ZoneInfo("US/Eastern"))
    result = provider.now()
    assert result.tzinfo is not None
    assert str(result.tzinfo) == "US/Eastern"


def test_tz_name_returns_iana_name():
    provider = TimeProvider(tz=ZoneInfo("Europe/Warsaw"))
    assert provider.tz_name == "Europe/Warsaw"


def test_source_defaults_to_server():
    provider = TimeProvider(tz=ZoneInfo("UTC"))
    assert provider.source == TimestampSource.SERVER


def test_source_user_timezone():
    provider = TimeProvider(tz=ZoneInfo("UTC"), source=TimestampSource.USER_TIMEZONE)
    assert provider.source == TimestampSource.USER_TIMEZONE
