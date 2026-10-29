from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.message_metadata import TimestampSource, get_metadata_from_state
from quickapp.common.time_provider import TimeProvider, TimezoneLabel
from quickapp.timestamp_tooling._current_timestamp_tool import _CurrentTimestampTool
from quickapp.timestamp_tooling._tool_configs import CURRENT_TIMESTAMP_TOOL_CONFIG


def _build_tool(time_provider: TimeProvider | None = None) -> _CurrentTimestampTool:
    tp = time_provider or TimeProvider()
    tool = _CurrentTimestampTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=CURRENT_TIMESTAMP_TOOL_CONFIG,
        perf_timer=MagicMock(),
        time_provider=tp,
    )
    return tool


class TestCurrentTimestampTool:
    @pytest.mark.asyncio
    async def test_returns_utc_by_default(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None)

        assert "UTC" in result.content
        assert "source=fallback" in result.content
        assert "T" in result.content  # ISO 8601

    @pytest.mark.asyncio
    async def test_defaults_to_user_zone_from_time_provider(self):
        tp = TimeProvider(
            tz=ZoneInfo("Europe/Kyiv"), source=TimestampSource.REQUEST, label=TimezoneLabel.USER
        )
        tool = _build_tool(tp)
        result = await tool._run_in_stage_async(stage_wrapper=None)

        assert "(Europe/Kyiv, source=user)" in result.content
        metadata = get_metadata_from_state(result.state)
        assert metadata is not None and metadata.timestamp is not None
        assert metadata.timestamp.timestamp_source == TimestampSource.REQUEST

    @pytest.mark.asyncio
    async def test_timezone_conversion_has_no_source_label(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, timezone="Asia/Tokyo")

        assert result.content.endswith("+09:00 (Asia/Tokyo)")
        assert "source=" not in result.content
        metadata = get_metadata_from_state(result.state)
        assert metadata is not None and metadata.timestamp is not None
        assert metadata.timestamp.timestamp_source is None
        assert metadata.timestamp.timezone_name == "Asia/Tokyo"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["", "   "])
    async def test_empty_timezone_argument_counts_as_absent(self, value):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, timezone=value)

        assert "(UTC, source=fallback)" in result.content

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["Invalid/Timezone", "europe/warsaw", "localtime"])
    async def test_invalid_timezone_raises_parameter_error(self, value):
        tool = _build_tool()
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._run_in_stage_async(stage_wrapper=None, timezone=value)
        assert excinfo.value.parameter_name == "timezone"

    @pytest.mark.asyncio
    async def test_result_has_state_with_metadata(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None)

        assert result.state is not None
        assert "_message_metadata" in result.state

    @pytest.mark.asyncio
    async def test_content_type_is_text_plain(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None)

        assert result.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_stage_wrapper_receives_result(self):
        tool = _build_tool()
        mock_wrapper = MagicMock()
        result = await tool._run_in_stage_async(stage_wrapper=mock_wrapper)

        mock_wrapper.add_result.assert_called_once_with(result)
