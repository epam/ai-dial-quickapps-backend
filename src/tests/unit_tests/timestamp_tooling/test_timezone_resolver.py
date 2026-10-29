import logging
from zoneinfo import ZoneInfo

from quickapp.common.message_metadata import TimestampSource
from quickapp.common.time_provider import TimezoneLabel
from quickapp.timestamp_tooling._timezone_resolver import resolve_user_timezone


class TestResolveUserTimezone:
    def test_valid_header_wins_over_app_default(self):
        resolved = resolve_user_timezone("Europe/Kyiv", "Europe/Warsaw")

        assert resolved.tz == ZoneInfo("Europe/Kyiv")
        assert resolved.source == TimestampSource.REQUEST
        assert resolved.label == TimezoneLabel.USER

    def test_header_is_stripped(self):
        resolved = resolve_user_timezone("  Asia/Tokyo ", None)

        assert resolved.tz == ZoneInfo("Asia/Tokyo")
        assert resolved.label == TimezoneLabel.USER

    def test_absent_header_uses_app_default(self):
        resolved = resolve_user_timezone(None, "Europe/Warsaw")

        assert resolved.tz == ZoneInfo("Europe/Warsaw")
        assert resolved.source == TimestampSource.DEFAULT
        assert resolved.label == TimezoneLabel.APP_DEFAULT

    def test_empty_header_counts_as_absent(self):
        resolved = resolve_user_timezone("   ", "Europe/Warsaw")

        assert resolved.label == TimezoneLabel.APP_DEFAULT

    def test_invalid_header_falls_back_to_app_default(self):
        resolved = resolve_user_timezone("UTC+3", "Europe/Warsaw")

        assert resolved.tz == ZoneInfo("Europe/Warsaw")
        assert resolved.label == TimezoneLabel.APP_DEFAULT

    def test_nothing_usable_falls_back_to_utc(self):
        resolved = resolve_user_timezone("europe/kyiv", None)

        assert resolved.tz == ZoneInfo("UTC")
        assert resolved.source == TimestampSource.DEFAULT
        assert resolved.label == TimezoneLabel.FALLBACK

    def test_invalid_header_is_logged_without_its_value(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="quickapp.timestamp_tooling._timezone_resolver"):
            resolve_user_timezone("Secret/Value", None)

        assert "X-Timezone" in caplog.text
        assert "length=12" in caplog.text
        assert "Secret/Value" not in caplog.text
