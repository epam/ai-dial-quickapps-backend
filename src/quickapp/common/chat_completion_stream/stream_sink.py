"""DI-pluggable side effects for chat-completion stream consumption."""

from __future__ import annotations

from abc import ABC, abstractmethod

from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint, NormalizedChoiceDelta


class ChatStreamSink(ABC):
    """Side effect applied to every stream event. Inactive sinks early-return themselves."""

    @abstractmethod
    def on_stream_start(self) -> None: ...

    @abstractmethod
    def on_delta(self, delta: NormalizedChoiceDelta) -> None: ...

    @abstractmethod
    def on_usage(self, usage: ChunkUsageFootprint) -> None: ...

    @abstractmethod
    def on_stream_success(self) -> None: ...

    @abstractmethod
    def on_stream_failure(self) -> None: ...
