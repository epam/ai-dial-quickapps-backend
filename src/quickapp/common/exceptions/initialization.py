from typing import ClassVar


class InitializationException(Exception):
    """Base class for any failure that should flow through the merged
    ``list[InitializationException]`` multiprovider to
    ``_InitializationErrorHandler`` for unified rendering.
    """

    is_hard: ClassVar[bool] = True
