from typing import Any
from unittest.mock import Mock

import pytest
from aidial_sdk.chat_completion import Attachment

from injector import AssistedBuilder

from quickapp.common import StagedBaseTool, CompletionResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.tool import AnyTool
from quickapp.config.tools.tool_fallback import ToolFallbackConfig
from quickapp.dial_core_services.dial_file_service import DialFileService


class CustomTestStagedBaseTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[BaseStageWrapper],
        tool_config: AnyTool,
        perf_timer: PerformanceTimer,
        result_to_return: CompletionResult | None = None,
        file_service: DialFileService = Mock(),
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,
            tool_config=tool_config,
            name="Test Tool",
            description="A test tool",
            perf_timer=perf_timer,
            file_service=file_service
        )
        self._result_to_return = result_to_return

    async def _run_in_stage_async(
        self, stage_wrapper, *args: Any, **kwargs: Any
    ) -> CompletionResult:
        if self._result_to_return is not None:
            return self._result_to_return
        return CompletionResult(content="response content", content_type="application/json")


@pytest.fixture
def mock_stage_wrapper_factory():
    mock_stage_wrapper = Mock(spec=BaseStageWrapper)
    mock_stage_wrapper.name = "test_stage"
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
    mock_config.display = None
    mock_config.fallback_configuration = ToolFallbackConfig(display_error_in_stage=True)
    return mock_config


@pytest.mark.asyncio
async def test_exception_handled_in_staged_base_tool(mock_stage_wrapper_factory, mock_tool_config):
    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_tool_config,
        perf_timer=Mock(),
    )
    ex = Exception("Test exception")
    mock_stage_wrapper = mock_stage_wrapper_factory.build()
    mock_stage_wrapper.add_parameters.side_effect = ex

    result = await tool.arun("tool_call_id_1", **{"param1": "value1"})
    assert result is not None


@pytest.mark.asyncio
async def test_exception_on_run(mock_stage_wrapper_factory, mock_tool_config):
    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_tool_config,
        perf_timer=Mock(),
    )
    with pytest.raises(NotImplementedError):
        tool._run("tool_call_id_1", **{"param1": "value1"})


@pytest.mark.asyncio
async def test_propagation_only_for_surviving_attachments(mock_stage_wrapper_factory):
    """An attachment that fails supported_types but matches propagate_types_to_choice
    should NOT be added to propagate_to_choice."""
    mock_config = Mock()
    mock_config.display = None
    mock_config.fallback_configuration = ToolFallbackConfig(display_error_in_stage=True)
    mock_config.attachment = AttachmentConfig(
        supported_types=["image/*"],
        propagate_types_to_choice=["image/*", "text/plain"],
    )

    image_attachment = Attachment(type="image/png", title="image.png", data="img_data")
    text_attachment = Attachment(type="text/plain", title="readme.txt", data="text_data")

    result_to_return = CompletionResult(
        content="result",
        content_type="text/plain",
        attachments=[image_attachment, text_attachment],
    )

    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_config,
        perf_timer=Mock(),
        result_to_return=result_to_return,
    )

    result = await tool.arun("call-1")

    # text/plain fails supported_types=["image/*"], so only image survives
    assert len(result.attachments) == 1
    assert result.attachments[0].type == "image/png"

    # text/plain matches propagate_types_to_choice but was filtered out by supported_types,
    # so it should NOT appear in propagate_to_choice
    assert len(result.propagate_to_choice) == 1
    assert result.propagate_to_choice[0].type == "image/png"
