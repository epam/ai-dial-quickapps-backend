class DialSkillFileReadError(Exception):
    """Raised when a file of a DIAL skill resource cannot be read.

    The message is rendered verbatim to the model (via the ``read_skill`` tool)
    or to the user (via the initialization-issues stage), so it must always
    carry a reason — several httpx transport errors and ``TimeoutError`` have an
    empty ``str()``, which is what ``describe_exception`` guards against.
    """

    def __init__(self, file_path: str, reason: str) -> None:
        self.file_path = file_path
        self.reason = reason
        super().__init__(f"Failed to read '{file_path}' from DIAL: {reason}")


class DialSkillFileTooLargeError(DialSkillFileReadError):
    """Raised when a fetched file exceeds ``DIAL_SKILLS_FILE_MAX_BYTES``."""

    def __init__(self, file_path: str, size: int, limit: int) -> None:
        super().__init__(file_path, f"file is {size} bytes, over the {limit} byte limit")


class DialSkillFileNotTextError(DialSkillFileReadError):
    """Raised when a fetched file is not valid UTF-8 text."""

    def __init__(self, file_path: str) -> None:
        super().__init__(file_path, "file is not UTF-8 text")


def describe_exception(exc: BaseException) -> str:
    """Return a non-empty description of *exc*.

    ``str()`` is empty for ``TimeoutError`` and several httpx transport errors,
    which would otherwise produce a reason-less "Failed to read ...: " message.
    """
    return str(exc) or type(exc).__name__
