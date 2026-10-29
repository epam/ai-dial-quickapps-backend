from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aidial_sdk.chat_completion import Message, Role

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

    def test_utc_fallback_without_header(self):
        tp = _provide(_app_config(ToolCallTimestampConfig()), None)

        assert tp.tz == ZoneInfo("UTC")
        assert tp.label == TimezoneLabel.FALLBACK

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
