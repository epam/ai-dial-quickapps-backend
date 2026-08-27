import time
from typing import Any
from unittest.mock import Mock

import pytest
from aidial_sdk.chat_completion import Attachment, Status
from injector import AssistedBuilder

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.adopted_tool_stage import AdoptedToolStage
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry
from quickapp.common.staged_base_tool import _MAX_RETRY_MESSAGE_CHARS, _cap_retry_message
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.tool import AnyTool
from quickapp.config.tools.tool_fallback import ToolFallbackConfig


class CustomTestStagedBaseTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[BaseStageWrapper],
        tool_config: AnyTool,
        perf_timer: PerformanceTimer,
        deferred_stage_close_registry: DeferredStageCloseRegistry | None = None,
        result_to_return: ToolCallResult | None = None,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,
            tool_config=tool_config,
            name="Test Tool",
            description="A test tool",
            perf_timer=perf_timer,
            deferred_stage_close_registry=(
                deferred_stage_close_registry or DeferredStageCloseRegistry()
            ),
            stage_display_level=stage_display_level,
        )
        self._result_to_return = result_to_return

    async def _run_in_stage_async(
        self, stage_wrapper, tool_call_id: str | None, *args: Any, **kwargs: Any
    ) -> ToolCallResult:
        if self._result_to_return is not None:
            return self._result_to_return
        return ToolCallResult(content="response content", content_type="application/json")


class FailingTestTool(StagedBaseTool):
    """A tool that always raises in _run_in_stage_async — used to verify that
    exceptions are caught and converted to fallback results even when the stage
    is suppressed (stage_display_level=error)."""

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[BaseStageWrapper],
        tool_config: AnyTool,
        perf_timer: PerformanceTimer,
        error: Exception,
        deferred_stage_close_registry: DeferredStageCloseRegistry | None = None,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,
            tool_config=tool_config,
            name="Failing Tool",
            description="A tool that always fails",
            perf_timer=perf_timer,
            deferred_stage_close_registry=(
                deferred_stage_close_registry or DeferredStageCloseRegistry()
            ),
            stage_display_level=stage_display_level,
        )
        self._error = error

    async def _run_in_stage_async(
        self, stage_wrapper, tool_call_id: str | None, *args: Any, **kwargs: Any
    ) -> ToolCallResult:
        raise self._error


def _make_tool_config(show: bool | None = None) -> Mock:
    """Create a tool config mock. show=None means display=None (unset)."""
    mock_config = Mock(spec=AnyTool)
    mock_config.fallback_configuration = ToolFallbackConfig(display_error_in_stage=True)
    if show is None:
        mock_config.display = None
    else:
        mock_stage = Mock()
        mock_stage.show = show
        mock_display = Mock()
        mock_display.stage = mock_stage
        mock_config.display = mock_display
    return mock_config


@pytest.fixture
def mock_stage_wrapper_factory():
    mock_stage_wrapper = Mock(spec=BaseStageWrapper)
    mock_stage_wrapper.name = "test_stage"
    mock_stage_wrapper.add_parameters = Mock()
    mock_stage_wrapper.append_title_from_params = Mock()
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

    result_to_return = ToolCallResult(
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


@pytest.mark.asyncio
async def test_media_type_substitution_applied(mock_stage_wrapper_factory):
    """Attachments that pass supported_types should have their type substituted
    according to media_type_substitution mapping."""
    mock_config = Mock()
    mock_config.display = None
    mock_config.fallback_configuration = ToolFallbackConfig(display_error_in_stage=True)
    mock_config.attachment = AttachmentConfig(
        supported_types=["image/*"],
        propagate_types_to_choice=["image/*"],
        media_type_substitution={"image/png": "image/webp"},
    )

    attachment = Attachment(type="image/png", title="photo.png", data="img_data")

    result_to_return = ToolCallResult(
        content="result",
        content_type="text/plain",
        attachments=[attachment],
    )

    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_config,
        perf_timer=Mock(),
        result_to_return=result_to_return,
    )

    result = await tool.arun("call-1")

    assert len(result.attachments) == 1
    assert result.attachments[0].type == "image/webp"


@pytest.mark.asyncio
async def test_media_type_substitution_not_applied_when_no_match(mock_stage_wrapper_factory):
    """Attachments whose type is not in the substitution mapping keep their original type."""
    mock_config = Mock()
    mock_config.display = None
    mock_config.fallback_configuration = ToolFallbackConfig(display_error_in_stage=True)
    mock_config.attachment = AttachmentConfig(
        supported_types=["image/*"],
        propagate_types_to_choice=["image/*"],
        media_type_substitution={"image/png": "image/webp"},
    )

    attachment = Attachment(type="image/jpeg", title="photo.jpg", data="img_data")

    result_to_return = ToolCallResult(
        content="result",
        content_type="text/plain",
        attachments=[attachment],
    )

    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_config,
        perf_timer=Mock(),
        result_to_return=result_to_return,
    )

    result = await tool.arun("call-1")

    assert len(result.attachments) == 1
    assert result.attachments[0].type == "image/jpeg"


@pytest.mark.asyncio
async def test_propagation_uses_substituted_type(mock_stage_wrapper_factory):
    """After substitution, propagate_types_to_choice should match against the NEW type."""
    mock_config = Mock()
    mock_config.display = None
    mock_config.fallback_configuration = ToolFallbackConfig(display_error_in_stage=True)
    mock_config.attachment = AttachmentConfig(
        supported_types=["image/*"],
        propagate_types_to_choice=["application/custom"],
        media_type_substitution={"image/png": "application/custom"},
    )

    attachment = Attachment(type="image/png", title="chart.png", data="img_data")

    result_to_return = ToolCallResult(
        content="result",
        content_type="text/plain",
        attachments=[attachment],
    )

    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_config,
        perf_timer=Mock(),
        result_to_return=result_to_return,
    )

    result = await tool.arun("call-1")

    # The attachment survives (image/png passes supported_types=["image/*"])
    assert len(result.attachments) == 1
    # Its type was substituted
    assert result.attachments[0].type == "application/custom"
    # Propagation check uses the substituted type, which matches propagate_types_to_choice
    assert len(result.propagate_to_choice) == 1
    assert result.propagate_to_choice[0].type == "application/custom"


@pytest.mark.asyncio
async def test_defer_stage_close_defers_exit_until_registry_flush(mock_stage_wrapper_factory):
    mock_stage_wrapper = mock_stage_wrapper_factory.build()
    registry = DeferredStageCloseRegistry()

    deferred_config = Mock(spec=AnyTool)
    deferred_config.display = ToolDisplayConfig(stage=ToolStageConfig(defer_close=True))
    deferred_config.fallback_configuration = ToolFallbackConfig(display_error_in_stage=True)

    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=deferred_config,
        perf_timer=Mock(),
        deferred_stage_close_registry=registry,
    )

    await tool.arun("call-1")

    mock_stage_wrapper.__exit__.assert_not_called()
    registry.flush()
    mock_stage_wrapper.__exit__.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "display_level,call_level,show,expect_suppressed",
    [
        (StageDisplayLevel.NONE, StageDisplayLevel.ERROR, None, True),
        (StageDisplayLevel.NONE, StageDisplayLevel.INFO, None, True),
        (StageDisplayLevel.NONE, StageDisplayLevel.DEBUG, None, True),
        (StageDisplayLevel.ERROR, StageDisplayLevel.ERROR, None, False),
        (StageDisplayLevel.ERROR, StageDisplayLevel.INFO, None, True),
        (StageDisplayLevel.ERROR, StageDisplayLevel.DEBUG, None, True),
        (StageDisplayLevel.INFO, StageDisplayLevel.ERROR, None, False),
        (StageDisplayLevel.INFO, StageDisplayLevel.INFO, None, False),
        (StageDisplayLevel.INFO, StageDisplayLevel.INFO, False, True),
        (StageDisplayLevel.INFO, StageDisplayLevel.DEBUG, None, True),
        (StageDisplayLevel.DEBUG, StageDisplayLevel.INFO, False, False),
        (StageDisplayLevel.DEBUG, StageDisplayLevel.ERROR, None, False),
        (StageDisplayLevel.DEBUG, StageDisplayLevel.DEBUG, None, False),
    ],
)
async def test_suppression_truth_table(
    display_level, call_level, show, expect_suppressed, mock_stage_wrapper_factory
):
    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=_make_tool_config(show),
        perf_timer=Mock(),
        stage_display_level=display_level,
    )

    await tool.arun("call-id", stage_level=call_level)

    if expect_suppressed:
        mock_stage_wrapper_factory.build.assert_not_called()
    else:
        mock_stage_wrapper_factory.build.assert_called_once()


@pytest.mark.asyncio
async def test_arun_with_adopted_stage_skips_add_parameters_when_code_was_streamed(
    mock_stage_wrapper_factory, mock_tool_config
):
    mock_stage_wrapper = mock_stage_wrapper_factory.build()
    adopted_stage_obj = Mock()
    start = time.perf_counter() - 5.0
    adopted = AdoptedToolStage(
        stage=adopted_stage_obj,
        start_time=start,
        request_body_streamed=True,
    )

    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_tool_config,
        perf_timer=Mock(),
    )

    result = await tool.arun(
        "call-1",
        adopted_stage=adopted,
        title="demo",
        code="print(1)",
    )

    assert result is not None
    mock_stage_wrapper_factory.build.assert_called_with(
        tool_config=mock_tool_config,
        stage_name=None,
        stage=adopted_stage_obj,
        already_open=True,
        start_time=start,
    )
    mock_stage_wrapper.add_parameters.assert_not_called()
    mock_stage_wrapper.append_title_from_params.assert_called_once()
    mock_stage_wrapper.__enter__.assert_called_once()
    mock_stage_wrapper.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_arun_with_adopted_stage_adds_parameters_when_nothing_streamed(
    mock_stage_wrapper_factory, mock_tool_config
):
    mock_stage_wrapper = mock_stage_wrapper_factory.build()
    adopted = AdoptedToolStage(stage=Mock(), start_time=time.perf_counter())
    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=mock_tool_config,
        perf_timer=Mock(),
    )

    await tool.arun("call-1", adopted_stage=adopted, foo="bar")

    mock_stage_wrapper.add_parameters.assert_called_once()
    mock_stage_wrapper.append_title_from_params.assert_not_called()


@pytest.mark.asyncio
async def test_suppressed_arun_discards_adopted_stage(mock_stage_wrapper_factory, mock_tool_config):
    adopted_stage_obj = Mock()
    adopted = AdoptedToolStage(stage=adopted_stage_obj, start_time=time.perf_counter())

    tool = CustomTestStagedBaseTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=_make_tool_config(show=False),
        perf_timer=Mock(),
        stage_display_level=StageDisplayLevel.INFO,
    )

    await tool.arun("call-1", adopted_stage=adopted, stage_level=StageDisplayLevel.INFO)

    mock_stage_wrapper_factory.build.assert_not_called()
    adopted_stage_obj.close.assert_called_once_with(status=Status.COMPLETED)


@pytest.mark.asyncio
async def test_error_during_suppressed_stage_opens_stage_and_returns_fallback(
    mock_stage_wrapper_factory,
):
    """When stage_display_level=error suppresses an INFO-level call and the tool
    raises, a stage must be opened on-the-fly to show the error, and the exception
    must be caught and converted to a fallback result — not propagated to the
    caller (which would crash the chat)."""
    error = RuntimeError("MCP tool failed")
    tool = FailingTestTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=_make_tool_config(),
        perf_timer=Mock(),
        error=error,
        stage_display_level=StageDisplayLevel.ERROR,
    )

    # Should NOT raise — the fallback processor should handle it
    result = await tool.arun("call-id", stage_level=StageDisplayLevel.INFO)

    # Stage wrapper was built on-the-fly for the error (even though the call was
    # initially suppressed)
    mock_stage_wrapper_factory.build.assert_called_once()

    on_the_fly_stage = mock_stage_wrapper_factory.build.return_value
    # The error was written into the on-the-fly stage
    on_the_fly_stage.add_exception.assert_called_once_with(error)
    # The stage was opened and closed
    on_the_fly_stage.__enter__.assert_called_once()
    on_the_fly_stage.__exit__.assert_called_once()
    # A result was returned (fallback), not an exception
    assert result is not None
    assert result.tool_call_id == "call-id"


@pytest.mark.asyncio
async def test_error_at_none_level_no_stage_and_returns_fallback(
    mock_stage_wrapper_factory,
):
    """When stage_display_level=none, no stage is created — not even for errors.
    The exception is still caught and converted to a fallback result."""
    error = RuntimeError("MCP tool failed")
    tool = FailingTestTool(
        stage_wrapper_builder=mock_stage_wrapper_factory,
        tool_config=_make_tool_config(),
        perf_timer=Mock(),
        error=error,
        stage_display_level=StageDisplayLevel.NONE,
    )

    # Should NOT raise — the fallback processor should handle it
    result = await tool.arun("call-id", stage_level=StageDisplayLevel.INFO)

    # No stage wrapper was built — not even on-the-fly for the error
    mock_stage_wrapper_factory.build.assert_not_called()
    # A result was returned (fallback), not an exception
    assert result is not None
    assert result.tool_call_id == "call-id"


class TestCapRetryMessage:
    """The retry instruction built from an ``InvalidToolCallParameterException`` message
    goes straight into the next LLM call. Any tool can author that message, so it is
    bounded — an accidental payload in one must not be able to blow the context window."""

    def test_short_message_passed_through_unchanged(self):
        assert _cap_retry_message("URL scheme not supported") == "URL scheme not supported"

    def test_message_at_the_limit_not_truncated(self):
        message = "x" * _MAX_RETRY_MESSAGE_CHARS
        assert _cap_retry_message(message) == message

    def test_oversized_message_truncated(self):
        message = "y" * (_MAX_RETRY_MESSAGE_CHARS + 5000)
        capped = _cap_retry_message(message)

        assert len(capped) < len(message)
        assert capped.endswith("... (truncated)")
        assert capped.startswith("y" * 100)
