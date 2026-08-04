from abc import ABC
from time import perf_counter
from types import TracebackType

from aidial_sdk.chat_completion import Stage

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.config.tools.base import BaseTool


class TimedStageWrapper(BaseStageWrapper, ABC):

    def __init__(
        self,
        stage: Stage,
        tool_config: BaseTool | None = None,
        stage_name: str | None = None,
        *,
        already_open: bool = False,
        start_time: float | None = None,
    ):
        super().__init__(
            stage=stage,
            tool_config=tool_config,
            stage_name=stage_name,
            already_open=already_open,
        )
        self.__start_time: float = 0
        self.__adopted_start_time = start_time

    def __enter__(self) -> BaseStageWrapper:
        self.__start_time = (
            self.__adopted_start_time if self.__adopted_start_time is not None else perf_counter()
        )
        return super().__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        end_time = perf_counter()
        self.append_stage_name(f" [{end_time - self.__start_time:.2f}s]")
        return super().__exit__(exc_type, exc, traceback)
