from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.message_metadata import TimestampSource
from quickapp.common.time_provider import TimezoneLabel
from quickapp.config.timestamp import ToolCallTimestampConfig
from quickapp.timestamp_tooling._timestamp_injection_transformer import (
    _TimestampInjectionTransformer,
)
from quickapp.timestamp_tooling.timestamp_module import TimestampModule
from tests.unit_tests.common.common import make_provider


def _app_config(timestamp: ToolCallTimestampConfig | None) -> Any:
    return SimpleNamespace(features=SimpleNamespace(timestamp=timestamp))


class TestProvideTimeProvider:
    def test_header_zone_is_used(self):
        tp = TimestampModule()._provide_time_provider("Asia/Tokyo")

        assert tp.tz == ZoneInfo("Asia/Tokyo")
        assert tp.source == TimestampSource.REQUEST
        assert tp.label == TimezoneLabel.USER

    def test_utc_fallback_without_header(self):
        tp = TimestampModule()._provide_time_provider(None)

        assert tp.tz == ZoneInfo("UTC")
        assert tp.label == TimezoneLabel.FALLBACK

    @pytest.mark.asyncio
    async def test_injected_timestamp_is_in_user_zone(self):
        transformer = _TimestampInjectionTransformer(
            time_provider=TimestampModule()._provide_time_provider("Asia/Tokyo"),
            enrichers_provider=make_provider([]),
        )

        result = await transformer.transform([Message(role=Role.USER, content="hi")])

        assert str(result[2].content).endswith("+09:00 (Asia/Tokyo, source=user)")


class TestMessageTransformersGating:
    def test_feature_on_returns_injection_transformer(self):
        transformer = MagicMock(spec=_TimestampInjectionTransformer)

        result = TimestampModule()._provide_message_transformers(
            _app_config(ToolCallTimestampConfig()), make_provider(transformer)
        )

        assert result == [transformer]

    @pytest.mark.parametrize("app_config", [_app_config(None), SimpleNamespace(features=None)])
    def test_feature_off_returns_empty_without_building(self, app_config):
        transformer_provider = MagicMock()

        result = TimestampModule()._provide_message_transformers(app_config, transformer_provider)

        assert result == []
        transformer_provider.get.assert_not_called()


class TestEnrichersGating:
    def test_feature_off_does_not_build_time_provider(self):
        time_provider = MagicMock()

        result = TimestampModule()._provide_enrichers(_app_config(None), time_provider)

        assert result == []
        time_provider.get.assert_not_called()
