from abc import ABC, abstractmethod


class LifecycleResource(ABC):

    @abstractmethod
    async def start(self) -> None:  # pragma: no cover
        ...

    @abstractmethod
    async def stop(self) -> None:  # pragma: no cover
        ...
