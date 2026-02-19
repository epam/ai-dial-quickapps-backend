from zoneinfo import ZoneInfo

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
