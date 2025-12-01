class _PyInterpreterError(Exception):
    """Base PyInterpreter Error"""


class _PyInterpreterSessionError(_PyInterpreterError):
    """Provides info if something wrong with PyInterpreter Session"""


class _PyInterpreterWrongRequestStateError(_PyInterpreterError):
    """Provides info if something wrong with state that was passed to PyInterpreter"""


class _PyInterpreterTimeOutError(_PyInterpreterError):
    """Provides info if something wrong with state that was passed to PyInterpreter"""
