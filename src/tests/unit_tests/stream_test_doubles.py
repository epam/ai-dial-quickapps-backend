"""Real SDK / wrapper types for tests that construct ``ChatStreamConfig``."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from aidial_sdk.chat_completion import Choice, Stage

from quickapp.common import ToolCallResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper


class SpyChoice(Choice):
    """Opened :class:`~aidial_sdk.chat_completion.Choice` with call recording for assertions."""

    def __init__(self) -> None:
        super().__init__(asyncio.Queue(), 0)
        self.open()
        self.append_content_calls: list[str] = []
        self.add_attachment_kwargs: list[dict[str, Any]] = []
        self.set_state_calls: list[Any] = []
        self.created_stages: list[Stage] = []

    def append_content(self, content: str) -> None:
        self.append_content_calls.append(content)
        return super().append_content(content)

    def add_attachment(self, *args: Any, **kwargs: Any) -> None:
        if kwargs:
            self.add_attachment_kwargs.append(dict(kwargs))
        else:
            self.add_attachment_kwargs.append({"args": args})

    def set_state(self, state: Any) -> None:
        self.set_state_calls.append(state)
        return super().set_state(state)

    def create_stage(self, name: str | None = None) -> Stage:
        stage = super().create_stage(name)
        self.created_stages.append(stage)
        return stage

    def drain_queue(self) -> list[Any]:
        items: list[Any] = []
        while not self._queue.empty():  # noqa: SLF001 - test helper
            items.append(self._queue.get_nowait())
        return items


class DummyStageWrapper(BaseStageWrapper):
    """Minimal :class:`~quickapp.common.base_stage_wrapper.BaseStageWrapper` for unit tests."""

    def __init__(self) -> None:
        self.stage_mock = MagicMock()
        self.stage_mock.__enter__.return_value = self.stage_mock
        self.stage_mock.__exit__.return_value = False
        super().__init__(self.stage_mock, tool_config=None, stage_name="test")

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return ""

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return ""
