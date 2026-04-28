from abc import ABC
from typing import Any

from injector import AssistedBuilder, inject

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.config.tools.internal import InternalTool
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.text_file_tooling._stage_wrapper import _FileStageWrapper

GENERATED_FILES_ROOT = "generated-files/"


@inject
class _TextFileTool(StagedBaseTool, ABC):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_FileStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        dial_file_service: DialFileService,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self._dial_file_service = dial_file_service

    async def _download_text(self, file_url: str) -> str:
        try:
            data = await self._dial_file_service.download_file(file_url)
        except Exception as e:
            raise InvalidToolCallParameterException("file_url", f"File download failed: {e}") from e
        return data.decode("utf-8")

    async def _download_text_with_etag(self, file_url: str) -> tuple[str, str]:
        try:
            data, etag = await self._dial_file_service.download_file_with_etag(file_url)
        except Exception as e:
            raise InvalidToolCallParameterException("file_url", f"File download failed: {e}") from e
        return data.decode("utf-8"), etag
