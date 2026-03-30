from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from quickapp.common.message_metadata import TimestampSource
from quickapp.common.time_provider import TimeProvider


class TestTimeProvider:
    def test_now_returns_utc_by_default(self):
        provider = TimeProvider()
        result = provider.now()
        assert result.tzinfo is not None
        assert str(result.tzinfo) == "UTC"

    def test_now_returns_configured_timezone(self):
        provider = TimeProvider(tz=ZoneInfo("Asia/Tokyo"))
        result = provider.now()
        assert str(result.tzinfo) == "Asia/Tokyo"

    def test_tz_name_property(self):
        provider = TimeProvider(tz=ZoneInfo("Europe/Berlin"))
        assert provider.tz_name == "Europe/Berlin"

    def test_source_defaults_to_default(self):
        provider = TimeProvider()
        assert provider.source == TimestampSource.DEFAULT

    def test_source_can_be_request(self):
        provider = TimeProvider(source=TimestampSource.REQUEST)
        assert provider.source == TimestampSource.REQUEST

    def test_now_is_provider_not_snapshot(self):
        provider = TimeProvider()
        t1 = provider.now()
        t2 = provider.now()
        assert t2 >= t1

    def test_format_timestamp_uses_provider_defaults(self):
        provider = TimeProvider()
        dt = datetime(2026, 3, 24, 14, 30, 0, tzinfo=timezone.utc)
        result = provider.format_timestamp(dt)
        assert "2026-03-24T14:30:00+00:00" in result
        assert "UTC" in result
        assert "source=default" in result

    def test_format_timestamp_uses_datetime_timezone(self):
        provider = TimeProvider()
        tokyo = ZoneInfo("Asia/Tokyo")
        dt = datetime(2026, 3, 24, 14, 30, 0, tzinfo=tokyo)
        result = provider.format_timestamp(dt)
        assert "Asia/Tokyo" in result
