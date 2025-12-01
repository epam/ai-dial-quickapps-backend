from typing import Any
from unittest.mock import Mock, patch

import pytest

from injector import AssistedBuilder

from quickapp.common import StagedBaseTool, CompletionResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.config.tools.tool import AnyTool
from quickapp.config.tools.tool_fallback import ToolFallbackConfig


class CustomTestStagedBaseTool(StagedBaseTool):

    def __init__(self, stage_wrapper_builder: AssistedBuilder[BaseStageWrapper], tool_config: AnyTool):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,
            tool_config=tool_config,
            name="Test Tool",
            description="A test tool"
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
    mock_config.fallback_configuration = ToolFallbackConfig(display_error_in_stage=True) # Add this line
    return mock_config


@pytest.mark.asyncio
async def test_exception_handled_in_staged_base_tool(mock_stage_wrapper_factory, mock_tool_config):
    tool = CustomTestStagedBaseTool(stage_wrapper_builder=mock_stage_wrapper_factory, tool_config=mock_tool_config)
    ex = Exception("Test exception")
    mock_stage_wrapper = mock_stage_wrapper_factory.build()
    mock_stage_wrapper.add_parameters.side_effect = ex
    ex_caught = False
    try:
        await tool.arun("tool_call_id_1",**{"param1": "value1"})
    except Exception as e:
        ex_caught = True

    assert ex_caught == False


@pytest.mark.asyncio
async def test_exception_on_run(mock_stage_wrapper_factory, mock_tool_config):
    tool = CustomTestStagedBaseTool(stage_wrapper_builder=mock_stage_wrapper_factory, tool_config=mock_tool_config)
    try:
        tool._run("tool_call_id_1", **{"param1": "value1"})
    except Exception as e:
        assert isinstance(e, NotImplementedError)
