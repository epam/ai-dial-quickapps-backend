from abc import ABC
from time import perf_counter
from types import TracebackType
from typing import Optional, Type

from aidial_sdk.chat_completion import Stage

from quickapp.config.tools.base import BaseTool

from .base_stage_wrapper import BaseStageWrapper


class TimedStageWrapper(BaseStageWrapper, ABC):

    def __init__(
        self, stage: Stage, tool_config: Optional[BaseTool] = None, stage_name: Optional[str] = None
    ):
        super().__init__(stage=stage, tool_config=tool_config, stage_name=stage_name)
        self.__start_time: float = 0

    def __enter__(self) -> BaseStageWrapper:
        self.__start_time = perf_counter()
        return super().__enter__()

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        end_time = perf_counter()
        self.append_stage_name(f" [{end_time - self.__start_time:.2f}s]")
        return super().__exit__(exc_type, exc, traceback)
