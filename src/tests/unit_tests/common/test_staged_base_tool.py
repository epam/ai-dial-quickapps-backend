from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock

import pytest

from injector import AssistedBuilder

from quickapp.common import StagedBaseTool, CompletionResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.message_metadata import MESSAGE_METADATA_KEY, MessageMetadata
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.tools.tool import AnyTool
from quickapp.config.tools.tool_fallback import ToolFallbackConfig


class CustomTestStagedBaseTool(StagedBaseTool):

    def __init__(self, stage_wrapper_builder: AssistedBuilder[BaseStageWrapper], tool_config: AnyTool, perf_timer: PerformanceTimer):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,
            tool_config=tool_config,
            name="Test Tool",
            description="A test tool",
            perf_timer=perf_timer
        )

    async def _run_in_stage_async(self, stage_wrapper, *args: Any, **kwargs: Any) -> CompletionResult:
        return CompletionResult(
            content="response content", content_type="application/json"
        )


@pytest.fixture
def mock_stage_wrapper_factory():
    mock_stage_wrapper = Mock(spec=BaseStageWrapper)
    mock_stage_wrapper.add_parameters = Mock()
    mock_stage_wrapper.add_exception = Mock()
    mock_stage_wrapper.__enter__ = Mock(return_value=mock_stage_wrapper)
    mock_stage_wrapper.__exit__ = Mock(return_value=False)

    factory = Mock()
    factory.build = Mock(return_value=mock_stage_wrapper)
    return factory

@pytest.fixture
def mock_tool_config():
    mock_config = Mock(spec=AnyTool)
    mock_config.display = None
    mock_config.fallback_configuration = ToolFallbackConfig(display_error_in_stage=True)
    return mock_config


@pytest.mark.asyncio
async def test_exception_handled_in_staged_base_tool(mock_stage_wrapper_factory, mock_tool_config):
    tool = CustomTestStagedBaseTool(stage_wrapper_builder=mock_stage_wrapper_factory, tool_config=mock_tool_config, perf_timer=Mock())
    ex = Exception("Test exception")
    mock_stage_wrapper = mock_stage_wrapper_factory.build()
    mock_stage_wrapper.add_parameters.side_effect = ex
    ex_caught = False
    try:
        await tool.arun("tool_call_id_1",**{"param1": "value1"})
    except Exception as e:
        ex_caught = True

    assert not ex_caught


@pytest.mark.asyncio
async def test_exception_on_run(mock_stage_wrapper_factory, mock_tool_config):
    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_tool_config,
        perf_timer=Mock(),
    )
    with pytest.raises(NotImplementedError):
        tool._run("tool_call_id_1", param1="value1")


@pytest.mark.asyncio
async def test_arun_enriches_result_with_metadata(mock_stage_wrapper_factory, mock_tool_config):
    mock_tool_config.display = Mock()
    mock_tool_config.display.stage = Mock()
    mock_tool_config.display.stage.show = False
    tool = CustomTestStagedBaseTool(stage_wrapper_builder=mock_stage_wrapper_factory, tool_config=mock_tool_config, perf_timer=Mock())
    result = await tool.arun("tool_call_id_1")
    assert result.state is not None
    assert MESSAGE_METADATA_KEY in result.state
    metadata = result.state[MESSAGE_METADATA_KEY]
    assert "response_timestamp" in metadata


class PresetMetadataTool(StagedBaseTool):
    preset_timestamp: datetime

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[BaseStageWrapper],
        tool_config: AnyTool,
        perf_timer: PerformanceTimer,
        preset_timestamp: datetime,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,
            tool_config=tool_config,
            name="Preset Metadata Tool",
            description="A tool that pre-sets metadata",
            perf_timer=perf_timer,
            preset_timestamp=preset_timestamp,
        )

    async def _run_in_stage_async(
        self, stage_wrapper, *args: Any, **kwargs: Any
    ) -> CompletionResult:
        metadata = MessageMetadata(response_timestamp=self.preset_timestamp)
        return CompletionResult(
            content="response",
            content_type="text/plain",
            state=metadata.to_state_entry(),
        )


@pytest.mark.asyncio
async def test_arun_preserves_preset_metadata(mock_stage_wrapper_factory, mock_tool_config):
    mock_tool_config.display = Mock()
    mock_tool_config.display.stage = Mock()
    mock_tool_config.display.stage.show = False
    preset_ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    tool = PresetMetadataTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_tool_config,
        perf_timer=Mock(),
        preset_timestamp=preset_ts,
    )
    result = await tool.arun("tool_call_id_1")
    assert result.state is not None
    restored = MessageMetadata.from_state(result.state)
    assert restored.response_timestamp == preset_ts
