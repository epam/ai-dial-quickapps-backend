from typing import Any

from aidial_sdk.chat_completion import Attachment
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from quickapp.agent._stage_delta_types import get_stage_index

from .accumulated_tool_call import AccumulatedToolCall


class _AccumulatedStageData:
    """Accumulates stage deltas by index (name parts, content, attachments, status)."""

    __slots__ = ("name_parts", "content", "attachments", "status")

    def __init__(self) -> None:
        self.name_parts: list[str] = []
        self.content = ""
        self.attachments: list[dict[str, Any]] = []
        self.status: str | None = None

    def append_delta(self, item: dict[str, Any]) -> None:
        if "name" in item and item["name"] is not None:
            self.name_parts.append(str(item["name"]))
        if "title" in item and item["title"] is not None:
            self.name_parts.append(str(item["title"]))
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


class AssistantCallResult:
    def __init__(self):
        self.__content = ""
        self.__attachments: list[Attachment] = []
        self.__accumulated_tool_calls: dict[int, AccumulatedToolCall] = {}
        self.__usage: Usage | None = None
        self.__stages_by_index: dict[int, _AccumulatedStageData] = {}
        self.__state: dict[str, Any] = {}

    @property
    def content(self):
        return self.__content

    def append_content(self, content: str) -> None:
        self.__content += content

    @property
    def attachments(self):
        return self.__attachments

    def append_attachment(self, attachment: Attachment) -> None:
        self.__attachments.append(attachment)

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
    def usage(self):
        return self.__usage

    def set_usage(self, usage: Usage) -> None:
        self.__usage = usage

    @property
    def stages(self) -> list[dict[str, Any]]:
        """Stages accumulated from stream, sorted by index."""
        if not self.__stages_by_index:
            return []
        return [self.__stages_by_index[idx].to_dict(idx) for idx in sorted(self.__stages_by_index)]

    def append_stage_delta(self, item: dict[str, Any], position: int) -> None:
        """Merge a stage delta into the stage at the given index."""
        idx = get_stage_index(item, position)
        if idx not in self.__stages_by_index:
            self.__stages_by_index[idx] = _AccumulatedStageData()
        self.__stages_by_index[idx].append_delta(item)

    @property
    def state(self) -> dict[str, Any]:
        """State captured from the assistant stream (copy)."""
        return dict(self.__state)

    def merge_state(self, state_update: dict[str, Any]) -> None:
        """Merge state updates from a chunk into captured state."""
        if state_update:
            self.__state.update(state_update)
