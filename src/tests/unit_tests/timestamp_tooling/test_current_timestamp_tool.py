from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.message_metadata import MESSAGE_METADATA_KEY
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.time_provider import TimeProvider
from quickapp.config.tools.tool import AnyTool
from quickapp.timestamp_tooling._current_timestamp_tool import _CurrentTimestampTool


@pytest.fixture
def mock_time_provider():
    provider = Mock(spec=TimeProvider)
    provider.now.return_value = datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
    return provider


@pytest.fixture
def mock_stage_wrapper_factory():
    mock_stage_wrapper = Mock(spec=BaseStageWrapper)
    mock_stage_wrapper.add_parameters = Mock()
    mock_stage_wrapper.add_result = Mock()
    mock_stage_wrapper.add_exception = Mock()
    mock_stage_wrapper.__enter__ = Mock(return_value=mock_stage_wrapper)
    mock_stage_wrapper.__exit__ = Mock(return_value=False)

    factory = Mock()
    factory.build = Mock(return_value=mock_stage_wrapper)
    return factory


@pytest.fixture
def mock_tool_config():
    mock_config = Mock(spec=AnyTool)
    mock_config.display = Mock()
    mock_config.display.stage = Mock()
    mock_config.display.stage.show = False
    mock_config.fallback_configuration = None
    return mock_config


@pytest.fixture
def tool(mock_stage_wrapper_factory, mock_tool_config, mock_time_provider):
    return _CurrentTimestampTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_tool_config,
        perf_timer=Mock(spec=PerformanceTimer),
        time_provider=mock_time_provider,
        name="current_timestamp",
        description="Returns the current timestamp",
    )


@pytest.mark.asyncio
async def test_run_in_stage_returns_iso_content(tool, mock_time_provider):
    result = await tool._run_in_stage_async(None)
    assert result.content == "2026-01-15T12:30:00+00:00"
    assert result.content_type == "text/plain"
    mock_time_provider.now.assert_called_once()


@pytest.mark.asyncio
async def test_arun_sets_metadata_in_state(tool):
    result = await tool.arun("test_call_id")
    assert result.tool_call_id == "test_call_id"
    assert result.state is not None
    assert MESSAGE_METADATA_KEY in result.state
    metadata = result.state[MESSAGE_METADATA_KEY]
    assert "response_timestamp" in metadata
