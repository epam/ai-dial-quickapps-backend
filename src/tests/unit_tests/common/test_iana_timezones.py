from zoneinfo import ZoneInfo

import pytest

from quickapp.common.iana_timezones import (
    is_valid_iana_timezone,
    normalize_timezone_name,
    parse_timezone,
)


class TestIsValidIanaTimezone:
    @pytest.mark.parametrize(
        "name", ["Europe/Kyiv", "Europe/Kiev", "Asia/Calcutta", "UTC", "America/New_York"]
    )
    def test_accepts_canonical_names_and_aliases(self, name):
        assert is_valid_iana_timezone(name)

    @pytest.mark.parametrize(
        "name",
        [
            "europe/warsaw",  # ZoneInfo accepts this on case-insensitive filesystems
            "localtime",  # would resolve to the server's zone
            "Factory",
            "UTC+3",
            "+03:00",
            "../etc/passwd",
            "/etc/localtime",
            "Nope/Zone",
            "",
            "a" * 300,
        ],
    )
    def test_rejects_non_iana_names(self, name):
        assert not is_valid_iana_timezone(name)


class TestNormalizeTimezoneName:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            (" Europe/Kyiv ", "Europe/Kyiv"),
            ("Asia/Tokyo", "Asia/Tokyo"),
        ],
    )
    def test_strips_and_treats_empty_as_absent(self, value, expected):
        assert normalize_timezone_name(value) == expected


class TestParseTimezone:
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_absent_or_blank_is_none(self, value):
        assert parse_timezone(value) is None

    def test_valid_name_is_stripped_and_parsed(self):
        assert parse_timezone(" Asia/Tokyo ") == ZoneInfo("Asia/Tokyo")

    @pytest.mark.parametrize("value", ["UTC+3", "europe/warsaw", "localtime", 3, ["Asia/Tokyo"]])
    def test_invalid_raises_value_error(self, value):
        with pytest.raises(ValueError):
            parse_timezone(value)
