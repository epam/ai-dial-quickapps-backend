import logging
from zoneinfo import ZoneInfo

import pytest

from quickapp.common.time_provider import TimezoneLabel
from quickapp.timestamp_tooling._timezone_resolver import resolve_user_timezone


class TestResolveUserTimezone:
    def test_valid_header_is_used(self):
        assert resolve_user_timezone("Europe/Kyiv") == (ZoneInfo("Europe/Kyiv"), TimezoneLabel.USER)

    def test_header_is_stripped(self):
        assert resolve_user_timezone("  Asia/Tokyo ") == (
            ZoneInfo("Asia/Tokyo"),
            TimezoneLabel.USER,
        )

    @pytest.mark.parametrize("value", [None, "", "   ", "UTC+3", "europe/kyiv", "localtime"])
    def test_absent_or_invalid_header_falls_back_to_utc(self, value):
        assert resolve_user_timezone(value) == (ZoneInfo("UTC"), TimezoneLabel.FALLBACK)

    def test_invalid_header_is_logged_without_its_value(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="quickapp.timestamp_tooling._timezone_resolver"):
            resolve_user_timezone("Secret/Value")

        assert "X-Timezone" in caplog.text
        assert "length=12" in caplog.text
        assert "Secret/Value" not in caplog.text
