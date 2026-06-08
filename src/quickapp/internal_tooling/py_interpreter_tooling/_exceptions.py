from quickapp.common.exceptions import ToolTimeoutError
from quickapp.common.tool_names import (
    INTERNAL_CODE_EXECUTION_PYTHON_INTERPRETER_TOOL_NAME as _PY_INTERPRETER_TOOL_NAME,
)


class _PyInterpreterError(Exception):
    """Base PyInterpreter Error"""


class _PyInterpreterSessionError(_PyInterpreterError):
    """Provides info if something wrong with PyInterpreter Session"""


class _PyInterpreterWrongRequestStateError(_PyInterpreterError):
    """Provides info if something wrong with state that was passed to PyInterpreter"""


class _PyInterpreterTimeOutError(ToolTimeoutError):
    """PyInterpreter client timeout. Extends `ToolTimeoutError`."""

    def __init__(
        self,
        timeout_seconds: float,
        tool_name: str = _PY_INTERPRETER_TOOL_NAME,
    ):
        super().__init__(tool_name=tool_name, timeout_seconds=timeout_seconds)
