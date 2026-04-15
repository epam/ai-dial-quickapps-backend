"""Mutable accumulator for OpenAI-style chat completion streams (orchestrator + deployment)."""

from __future__ import annotations

import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from quickapp.common._stage_delta_types import StageDeltaItem, get_stage_index
from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint
from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall

logger = logging.getLogger(__name__)


class _AccumulatedStageData:
    """Accumulates stage deltas by index (name parts, content, attachments, status)."""

    __slots__ = ("name_parts", "content", "attachments", "status")

    def __init__(self) -> None:
        self.name_parts: list[str] = []
        self.content = ""
        self.attachments: list[dict[str, Any]] = []
        self.status: str | None = None

    def append_delta(self, item: StageDeltaItem) -> None:
        if not isinstance(item, dict):
            return
        if "name" in item and item["name"] is not None:
            self.name_parts.append(str(item["name"]))
        if "content" in item and item["content"] is not None:
            self.content += str(item["content"])
        if "attachments" in item and item["attachments"]:
            self.attachments.extend(item["attachments"])
        if "status" in item and item["status"] is not None:
            self.status = str(item["status"])

    def to_dict(self, index: int | None = None) -> dict[str, Any]:
        name = " ".join(self.name_parts).strip() if self.name_parts else ""
        if not name and index is not None:
            name = f"Stage {index + 1}"
        return {
            "name": name or "Stage",
            "content": self.content,
            "attachments": self.attachments,
            "status": self.status,
        }


class Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


def ensure_attachment_url_or_data(attachment: Attachment) -> None:
    """Bugfix issue#16: if attachment has no data and no url, use reference_url as url or set empty data.

    Mutates SDK attachment objects in place (orchestrator + deployment stream handlers).
    """
    if attachment.data is None and attachment.url is None:
        if attachment.reference_url is None:
            attachment.data = ""
        else:
            attachment.url = attachment.reference_url


class ChatStreamAccumulator:
    """Collects text, custom content, usage, and optional tool/stage data from a stream."""

    def __init__(self) -> None:
        self.__content = ""
        self.__attachments: list[Attachment] = []
        self.__accumulated_tool_calls: dict[int, AccumulatedToolCall] = {}
        self.__usage: Usage | None = None
        self.__stages_by_index: dict[int, _AccumulatedStageData] = {}
        self.__state: dict[str, Any] = {}

    @property
    def content(self) -> str:
        return self.__content

    def append_content(self, content: str) -> None:
        self.__content += content

    @property
    def attachments(self) -> list[Attachment]:
        return self.__attachments

    def append_attachment(self, attachment: Attachment) -> None:
        self.__attachments.append(attachment)

    def extend_attachments(self, attachments: list[Attachment]) -> None:
        """Append SDK ``Attachment`` instances (parser normalizes to SDK type upstream)."""
        self.__attachments.extend(attachments)

    @property
    def tool_calls(self) -> list[AccumulatedToolCall] | None:
        values = list(self.__accumulated_tool_calls.values())
        return values if values else None

    def append_tool_call_delta(self, tool_call_delta: ChoiceDeltaToolCall) -> None:
        index = tool_call_delta.index
        if index not in self.__accumulated_tool_calls:
            self.__accumulated_tool_calls[index] = AccumulatedToolCall()
        self.__accumulated_tool_calls[index].append_delta(tool_call_delta)

    @property
    def usage(self) -> Usage | None:
        return self.__usage

    def set_usage(self, usage: Usage) -> None:
        self.__usage = usage

    def apply_usage_footprint(self, fp: ChunkUsageFootprint) -> None:
        if fp.prompt_tokens is not None and fp.completion_tokens is not None:
            self.__usage = Usage(fp.prompt_tokens, fp.completion_tokens)

    @property
    def stages(self) -> list[dict[str, Any]]:
        if not self.__stages_by_index:
            return []
        return [self.__stages_by_index[idx].to_dict(idx) for idx in sorted(self.__stages_by_index)]

    def append_stage_delta(self, item: StageDeltaItem, position: int) -> None:
        idx = get_stage_index(item, position)
        if idx not in self.__stages_by_index:
            self.__stages_by_index[idx] = _AccumulatedStageData()
        self.__stages_by_index[idx].append_delta(item)

    @property
    def state(self) -> dict[str, Any] | None:
        if not self.__state:
            return None
        return dict(self.__state)

    def merge_state(self, state_update: dict[str, Any]) -> None:
        if state_update:
            self.__state.update(state_update)

    @property
    def attachments_or_none(self) -> list[Attachment] | None:
        return self.__attachments if self.__attachments else None
