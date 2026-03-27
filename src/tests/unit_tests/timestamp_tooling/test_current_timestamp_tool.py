from unittest.mock import MagicMock

import pytest

from quickapp.common.time_provider import TimeProvider
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
        assert "source=default" in result.content
        assert "T" in result.content  # ISO 8601

    @pytest.mark.asyncio
    async def test_timezone_conversion(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, timezone="Asia/Tokyo")

        assert "Asia/Tokyo" in result.content
        assert "source=request" in result.content

    @pytest.mark.asyncio
    async def test_invalid_timezone_raises(self):
        tool = _build_tool()
        with pytest.raises(KeyError):
            await tool._run_in_stage_async(stage_wrapper=None, timezone="Invalid/Timezone")

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
