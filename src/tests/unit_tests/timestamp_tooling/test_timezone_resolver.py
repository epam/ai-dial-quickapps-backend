import logging
from zoneinfo import ZoneInfo

import pytest

from quickapp.common.message_metadata import TimestampSource
from quickapp.common.time_provider import TimezoneLabel
from quickapp.timestamp_tooling._timezone_resolver import resolve_user_timezone


class TestResolveUserTimezone:
    def test_valid_header_is_used(self):
        resolved = resolve_user_timezone("Europe/Kyiv")

        assert resolved.tz == ZoneInfo("Europe/Kyiv")
        assert resolved.source == TimestampSource.REQUEST
        assert resolved.label == TimezoneLabel.USER

    def test_header_is_stripped(self):
        resolved = resolve_user_timezone("  Asia/Tokyo ")

        assert resolved.tz == ZoneInfo("Asia/Tokyo")
        assert resolved.label == TimezoneLabel.USER

    @pytest.mark.parametrize("value", [None, "", "   ", "UTC+3", "europe/kyiv", "localtime"])
    def test_absent_or_invalid_header_falls_back_to_utc(self, value):
        resolved = resolve_user_timezone(value)

        assert resolved.tz == ZoneInfo("UTC")
        assert resolved.source == TimestampSource.DEFAULT
        assert resolved.label == TimezoneLabel.FALLBACK

    def test_invalid_header_is_logged_without_its_value(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="quickapp.timestamp_tooling._timezone_resolver"):
            resolve_user_timezone("Secret/Value")

        assert "X-Timezone" in caplog.text
        assert "length=12" in caplog.text
        assert "Secret/Value" not in caplog.text
