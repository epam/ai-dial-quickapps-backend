import base64
import logging
from typing import Any, Optional

from httpx import HTTPStatusError
from injector import AssistedBuilder, inject

from quickapp.common import DIAL_API_KEY, CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.dial_core_client import DialCoreClient
from quickapp.common.dial_settings import DialSettings
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.config.tools.internal import InternalTool
from quickapp.internal_tooling.content_download_tooling._content_download_stage_wrapper import (
    _ContentDownloaderStageWrapper,
)

logger = logging.getLogger(__name__)


def _return_result(result_str: str, stage_wrapper: Optional[BaseStageWrapper]):
    result = CompletionResult(
        content=result_str,
        content_type="text/plain",
    )
    if stage_wrapper:
        stage_wrapper.add_result(result)
    return result


@inject
class _ContentDownloadTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_ContentDownloaderStageWrapper],
        dial_settings: DialSettings,
        dial_api_key: DIAL_API_KEY,
        state_holder: StateHolder,
        tool_config: InternalTool,
        content_size_limit: int,
        perf_timer: PerformanceTimer,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            **kwargs,
        )
        self.__dial_settings: DialSettings = dial_settings
        self.__dial_api_key: DIAL_API_KEY = dial_api_key
        self.__stage_name_component = "Download content"
        self.__state_holder = state_holder
        self.__content_size_limit = content_size_limit

    def _pre_process_params(self, **kwargs: Any) -> Any:
        url: str = kwargs["url"]
        if url.startswith("/files"):
            # The url starts with '/files/...', and dial_core.get_file already have '/'. this removes first character
            url = url[1:]
        kwargs["url"] = url
        return kwargs

    async def _run_in_stage_async(
        self,
        stage_wrapper: Optional[BaseStageWrapper] = None,
        *args: Any,
        **kwargs: Any,
    ) -> CompletionResult:
        url: str = kwargs["url"]
        # Check state holder for the file content:
        logger.debug(f"content downloader url:{url}")
        base64_content = self.__state_holder.get_file_content(url=url)
        if base64_content is None:
            try:
                async with DialCoreClient(
                    api_key=self.__dial_api_key, base_url=self.__dial_settings.url
                ) as dial_core:
                    metadata = await dial_core.get_metadata(url)
                    size = metadata.get("contentLength") or 0
                    if size > self.__content_size_limit:
                        return _return_result(
                            f"Content can't be downloaded due to it's size {size}. It's greater than {self.__content_size_limit}. You can't proceed with this content",
                            stage_wrapper,
                        )

                    content_bytes = await dial_core.get_file(url)
                    base64_content = base64.b64encode(content_bytes).decode()
                    # Store base64_content into state_holder
                    self.__state_holder.store_file_content(url, base64_content)
            except HTTPStatusError as e:
                return _return_result(
                    f"Content wasn't stored due to exception: {e.response}. You can't proceed with this content",
                    stage_wrapper,
                )

        return _return_result(
            "Content stored. You MUST pass original URL to the tools in the format `files/<bucket_id>/<file_path>/<file_name>`, that requires binary format.",
            stage_wrapper,
        )
