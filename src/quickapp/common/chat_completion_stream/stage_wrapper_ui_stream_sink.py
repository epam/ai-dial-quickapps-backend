"""Stream UI side effects targeting a deployment tool stage wrapper."""

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.exceptions import ChatStreamWriteError
from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint, NormalizedChoiceDelta
from quickapp.common.chat_completion_stream.stream_result import ensure_attachment_url_or_data
from quickapp.common.chat_completion_stream.stream_sink import ChatStreamSink


class StageWrapperUiSink(ChatStreamSink):
    """Active when constructed with a non-None ``stage_wrapper``."""

    def __init__(
        self,
        stage_wrapper: BaseStageWrapper | None,
        *,
        stream_content: bool = True,
    ) -> None:
        self._stage_wrapper = stage_wrapper
        self._stream_content = stream_content

    def on_stream_start(self) -> None:
        if self._stage_wrapper is None:
            return
        self._stage_wrapper.append_stage_content("> #### Response:\n")

    def on_delta(self, delta: NormalizedChoiceDelta) -> None:
        wrapper = self._stage_wrapper
        if wrapper is None:
            return

        if delta.custom is not None and delta.custom.attachments:
            for attachment in delta.custom.attachments:
                ensure_attachment_url_or_data(attachment)
                try:
                    wrapper.add_attachment(attachment)
                except Exception as exc:
                    raise ChatStreamWriteError("Failed to stream attachment.") from exc

        if delta.content and self._stream_content:
            try:
                wrapper.append_stage_content(delta.content)
            except Exception as exc:  # pragma: no cover - defensive
                raise ChatStreamWriteError("Failed to stream content to destination") from exc

    def on_usage(self, usage: ChunkUsageFootprint) -> None:
        return

    def on_stream_success(self) -> None:
        return

    def on_stream_failure(self) -> None:
        return
