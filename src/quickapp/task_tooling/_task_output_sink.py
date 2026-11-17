"""Renders a task's output into the delegating agent's ``Task`` stage.

``Choice`` and ``Stage`` write every chunk to the ``ChunkQueue`` they were built with,
so intercepting that queue captures the task's whole output.
"""

import asyncio
import logging

from aidial_sdk.chat_completion import Attachment, Status
from aidial_sdk.chat_completion.chunks import (
    AttachmentChunk,
    AttachmentStageChunk,
    BaseChunk,
    ContentChunk,
    ContentStageChunk,
    EndChunk,
    ExceptionChunk,
    FinishStageChunk,
    FunctionCallChunk,
    FunctionToolCallChunk,
    NameStageChunk,
    StartStageChunk,
)

from quickapp.common.base_stage_wrapper import BaseStageWrapper

logger = logging.getLogger(__name__)

_STATUS_MARK = {Status.COMPLETED: "✓", Status.FAILED: "✗"}


class _TaskStage:
    """A stage the task opened, buffered until it closes.

    Buffered rather than streamed through because a task runs its tool calls
    concurrently (``ToolExecutor`` gathers them), so several of its stages are open at
    once. Streaming their content straight into the single parent stage would interleave
    two tool transcripts character by character. Emitting each on close keeps the
    rendering readable and still incremental — a line appears as each sub-task finishes.
    """

    def __init__(self, name: str | None) -> None:
        self.name = name or ""
        self.content: list[str] = []


_Chunk = BaseChunk | ExceptionChunk | EndChunk


class TaskOutputSink(asyncio.Queue[_Chunk]):
    """A ``ChunkQueue`` that renders the task's chunks into the parent tool stage.

    ``stage_wrapper`` is ``None`` when stage display is suppressed for the call; the sink
    then renders nothing but still collects attachments, so a task's chart is returned
    even with stages turned off.
    """

    def __init__(self, stage_wrapper: BaseStageWrapper | None) -> None:
        super().__init__()
        self._stage_wrapper = stage_wrapper
        self._stages: dict[int, _TaskStage] = {}
        self.attachments: list[Attachment] = []

    def put_nowait(self, item: _Chunk) -> None:
        """Consume the chunk instead of queueing it. Never raises into the task."""
        try:
            self._dispatch(item)
        except Exception:
            # A rendering failure must never fail the task: the answer the delegating agent
            # needs is read back off the task's messages, not off this stage.
            logger.warning("Failed to render task output chunk", exc_info=True)

    def _dispatch(self, chunk: _Chunk) -> None:
        match chunk:
            case ContentChunk():
                # The task's own prose between tool calls — the live progress signal.
                self._append(chunk.content)
            case StartStageChunk():
                self._stages[chunk.stage_index] = _TaskStage(chunk.name)
            case NameStageChunk():
                # Stage names arrive incrementally, so append rather than assign.
                self._stage(chunk.stage_index).name += chunk.name
            case ContentStageChunk():
                self._stage(chunk.stage_index).content.append(chunk.content)
            case FinishStageChunk():
                self._close_stage(chunk.stage_index, chunk.status)
            case AttachmentStageChunk():
                self._add_stage_attachment(chunk)
            case AttachmentChunk():
                # Choice-level attachment: hand it back on the tool result so
                # `StagedBaseTool.arun` can propagate it to the user's choice.
                self.attachments.append(_to_attachment(chunk))
            case FunctionToolCallChunk() | FunctionCallChunk():
                # Unreachable in practice — a task inherits no client-side tools, so its
                # EXTERNAL_TOOL_NAMES is empty. It has no channel to a user regardless.
                logger.warning("Task attempted a client-side tool call; dropped")
            case _:
                # State (tasks are stateless), usage, choice start/end, form schema,
                # discarded messages: nothing the delegating agent can use.
                return

    def _stage(self, index: int) -> _TaskStage:
        return self._stages.setdefault(index, _TaskStage(None))

    def _close_stage(self, index: int, status: Status) -> None:
        stage = self._stages.pop(index, None)
        if stage is None:
            return
        mark = _STATUS_MARK.get(status, "")
        self._append(f"\n\n**{stage.name.strip() or 'Step'}** {mark}\n")
        body = "".join(stage.content).strip()
        if body:
            self._append("\n".join(f"> {line}" for line in body.splitlines()) + "\n")

    def _add_stage_attachment(self, chunk: AttachmentStageChunk) -> None:
        if self._stage_wrapper is not None:
            self._stage_wrapper.add_attachment(_to_attachment(chunk))

    def _append(self, text: str) -> None:
        if self._stage_wrapper is not None and text:
            self._stage_wrapper.append_stage_content(text)


def _to_attachment(chunk: AttachmentChunk | AttachmentStageChunk) -> Attachment:
    """Convert a wire chunk back into the request-side attachment model."""
    return Attachment(
        type=chunk.type,
        title=chunk.title,
        data=chunk.data,
        url=chunk.url,
        reference_url=chunk.reference_url,
        reference_type=chunk.reference_type,
    )
