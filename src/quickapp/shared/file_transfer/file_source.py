from abc import ABC, abstractmethod


class FileSource(ABC):
    """Serves the bytes of URLs that are neither DIAL files nor external ``http(s)`` URLs.

    A feature contributes an implementation to ``list[FileSource]``; ``FileLoaderService``
    consults the sources before classifying a URL by scheme, so ``file_transfer`` knows
    nothing about the feature.
    """

    @abstractmethod
    def handles(self, url: str) -> bool: ...

    @abstractmethod
    async def load(self, url: str, parameter_name: str) -> bytes: ...
