from unittest.mock import Mock

import pytest

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.message_metadata import (
    MESSAGE_METADATA_KEY,
    MessageMetadata,
    USER_TIMEZONE_STATE_KEY,
)
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.tools.tool import AnyTool
from quickapp.timestamp_tooling._set_timezone_tool import _SetTimezoneTool


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
def tool(mock_stage_wrapper_factory, mock_tool_config):
    return _SetTimezoneTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_tool_config,
        perf_timer=Mock(spec=PerformanceTimer),
        name="set_user_timezone",
        description="Sets timezone",
    )


@pytest.mark.asyncio
async def test_valid_timezone_sets_state(tool):
    result = await tool._run_in_stage_async(None, timezone="Europe/Warsaw")
    assert result.state is not None
    assert result.state[USER_TIMEZONE_STATE_KEY] == "Europe/Warsaw"
    assert "Timezone set to Europe/Warsaw" in result.content


@pytest.mark.asyncio
async def test_reset_clears_timezone(tool):
    result = await tool._run_in_stage_async(None, timezone="reset")
    assert result.state is not None
    assert result.state[USER_TIMEZONE_STATE_KEY] is None
    assert "reset" in result.content.lower()


@pytest.mark.asyncio
async def test_invalid_timezone_returns_error(tool):
    result = await tool._run_in_stage_async(None, timezone="Not/A/Timezone")
    assert result.state is None
    assert "Invalid timezone" in result.content


@pytest.mark.asyncio
async def test_valid_timezone_sets_skip_time_annotation(tool):
    result = await tool._run_in_stage_async(None, timezone="Europe/Warsaw")
    assert result.state is not None
    assert MESSAGE_METADATA_KEY in result.state
    metadata = MessageMetadata.from_state(result.state)
    assert metadata.timestamp is not None
    assert metadata.timestamp.skip_time_annotation is True


@pytest.mark.asyncio
async def test_reset_sets_skip_time_annotation(tool):
    result = await tool._run_in_stage_async(None, timezone="reset")
    assert result.state is not None
    assert MESSAGE_METADATA_KEY in result.state
    metadata = MessageMetadata.from_state(result.state)
    assert metadata.timestamp is not None
    assert metadata.timestamp.skip_time_annotation is True
