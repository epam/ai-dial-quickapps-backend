from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aidial_sdk.chat_completion import Message, Role
from pydantic import ValidationError

from quickapp.common.message_metadata import TimestampSource
from quickapp.common.time_provider import TimeProvider, TimezoneLabel
from quickapp.config.timestamp import ToolCallTimestampConfig
from quickapp.timestamp_tooling._timestamp_injection_transformer import (
    _TimestampInjectionTransformer,
)
from quickapp.timestamp_tooling.timestamp_module import TimestampModule
from tests.unit_tests.common.common import make_provider


def _app_config(timestamp: ToolCallTimestampConfig | None) -> Any:
    return SimpleNamespace(features=SimpleNamespace(timestamp=timestamp))


def _provide(app_config: Any, header: str | None) -> TimeProvider:
    return TimestampModule()._provide_time_provider(app_config, header)


class TestProvideTimeProvider:
    def test_header_zone_is_used(self):
        tp = _provide(_app_config(ToolCallTimestampConfig()), "Asia/Tokyo")

        assert tp.tz == ZoneInfo("Asia/Tokyo")
        assert tp.source == TimestampSource.REQUEST
        assert tp.label == TimezoneLabel.USER

    def test_app_default_without_header(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        config = ToolCallTimestampConfig(default_timezone="Europe/Warsaw")
        tp = _provide(_app_config(config), None)

        assert tp.tz == ZoneInfo("Europe/Warsaw")
        assert tp.label == TimezoneLabel.APP_DEFAULT

    def test_feature_off_returns_utc_without_resolving(self):
        tp = _provide(_app_config(None), "Asia/Tokyo")

        assert tp.tz == ZoneInfo("UTC")
        assert tp.label == TimezoneLabel.FALLBACK

    def test_features_none_returns_utc(self):
        tp = _provide(SimpleNamespace(features=None), "Asia/Tokyo")

        assert tp.tz == ZoneInfo("UTC")

    @pytest.mark.asyncio
    async def test_injected_timestamp_is_in_user_zone(self):
        tp = _provide(_app_config(ToolCallTimestampConfig()), "Asia/Tokyo")
        transformer = _TimestampInjectionTransformer(
            time_provider=tp,
            config_provider=make_provider(_app_config(ToolCallTimestampConfig())),
            enrichers_provider=make_provider([]),
        )

        result = await transformer.transform([Message(role=Role.USER, content="hi")])

        assert str(result[2].content).endswith("+09:00 (Asia/Tokyo, source=user)")


class TestDefaultTimezoneConfig:
    def test_valid_zone_is_accepted(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        config = ToolCallTimestampConfig(default_timezone="Europe/Kiev")

        assert config.default_timezone == "Europe/Kiev"

    def test_unset_by_default(self):
        assert ToolCallTimestampConfig().default_timezone is None

    @pytest.mark.parametrize("value", ["UTC+3", "europe/warsaw", "localtime"])
    def test_invalid_zone_fails_validation(self, monkeypatch, value):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        with pytest.raises(ValidationError, match="default_timezone"):
            ToolCallTimestampConfig(default_timezone=value)
