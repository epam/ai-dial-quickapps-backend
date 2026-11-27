from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_BACKGROUND_EXECUTION: ContextVar[bool] = ContextVar("background_execution", default=False)


def is_background_execution() -> bool:
    """Whether the current call runs after its request ended, with no user to talk to."""
    return _BACKGROUND_EXECUTION.get()


@contextmanager
def background_execution() -> Iterator[None]:
    token = _BACKGROUND_EXECUTION.set(True)
    try:
        yield
    finally:
        _BACKGROUND_EXECUTION.reset(token)
