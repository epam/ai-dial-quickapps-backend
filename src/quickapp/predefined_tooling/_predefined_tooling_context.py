import threading

from quickapp.common.exceptions import ConfigResolutionException, InitializationException


class _PredefinedToolingContext:
    """Request-scoped collector for predefined-resolution exceptions, populated by
    ``PredefinedConfigResolver`` and consumed by ``_InitializationErrorHandler`` via the
    ``list[InitializationException]`` multiprovider.

    Mirrors ``_DialPromptSkillsContext`` in shape — a standalone class because
    ``ToolingContextBase._tools`` does not fit the resolver domain.
    """

    def __init__(self) -> None:
        self._exceptions: list[InitializationException] = []
        self._lock = threading.Lock()

    @property
    def exceptions(self) -> list[InitializationException]:
        return self._exceptions

    def append_exception(self, exception: ConfigResolutionException) -> None:
        with self._lock:
            self._exceptions.append(exception)
