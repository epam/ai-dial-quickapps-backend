from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.dial_settings import DialSettings
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.internal import InternalTool
from quickapp.internal_tooling.py_interpreter_tooling._exceptions import _PyInterpreterError
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_client import (
    _PyInterpreterClient,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PyInterpreterSettings,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_tool import _PyInterpreterTool
from quickapp.internal_tooling.py_interpreter_tooling.handlers.display_content_processor import (
    DisplayContentProcessor,
)
from quickapp.internal_tooling.py_interpreter_tooling.handlers.input_file_handler import (
    InputFileHandler,
)
from quickapp.internal_tooling.py_interpreter_tooling.handlers.session_manager import SessionManager

_TOOL_CONFIG = InternalTool(
    enabled=True,
    open_ai_tool=OpenAiToolConfig(
        type="function",
        function=OpenAiToolFunction(
            name="py_interpreter",
            description="Run code",
            parameters=OpenAiToolFunctionParameters(type=JsonTypeEnum.object, properties={}),
        ),
    ),
)


def _make_tool(client: MagicMock) -> _PyInterpreterTool:
    session_manager = MagicMock(spec=SessionManager)
    session_manager.get_session_id.return_value = "session-1"
    session_manager.ensure_valid_session = AsyncMock(return_value="session-1")
    settings = MagicMock(spec=_PyInterpreterSettings)
    settings.default_session_id = "default"
    return _PyInterpreterTool(
        stage_wrapper_builder=MagicMock(),
        messages_mixin=MagicMock(spec=MessagesMixin),
        client=client,
        py_interpreter_settings=settings,
        session_manager=session_manager,
        display_content_processor=MagicMock(spec=DisplayContentProcessor),
        dial_settings=MagicMock(spec=DialSettings),
        tool_config=_TOOL_CONFIG,
        perf_timer=MagicMock(),
        input_file_handler=MagicMock(spec=InputFileHandler),
        stage_display_level=StageDisplayLevel.NONE,
    )


def _failing_client(error: Exception) -> MagicMock:
    inner = MagicMock()
    inner.execute_code = AsyncMock(side_effect=error)
    client = MagicMock(spec=_PyInterpreterClient)
    client.__aenter__ = AsyncMock(return_value=inner)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_interpreter_error_propagates_from_the_tool_body():
    tool = _make_tool(_failing_client(_PyInterpreterError("session is broken")))

    with pytest.raises(_PyInterpreterError, match="session is broken"):
        await tool._run_in_stage_async(stage_wrapper=None, code="print(1)")


@pytest.mark.asyncio
async def test_interpreter_error_is_converted_to_error_result_by_the_base_tool():
    tool = _make_tool(_failing_client(_PyInterpreterError("session is broken")))

    result = await tool.arun("call-1", code="print(1)")

    assert result.is_error is True
    assert result.tool_call_id == "call-1"
    assert "session is broken" in result.content
