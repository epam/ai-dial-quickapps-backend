from typing import Any

from aidial_client._exception import DialException, EtagMismatchError, ResourceNotFoundError

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._base_file_tool import _DialFileTool


class _MoveFileTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        source: str = kwargs["source"]
        destination: str = kwargs["destination"]
        overwrite: bool = bool(kwargs.get("overwrite", False))

        self._reject_absolute_path("source", "move_file", source)
        self._reject_absolute_path("destination", "move_file", destination)

        source_url = await self._resolve_appdata_url(source)
        dest_url = await self._resolve_appdata_url(destination)
        dest_display = await self._to_display_path(dest_url)

        try:
            await self._dial_file_service.move(
                source_url=source_url, destination_url=dest_url, overwrite=overwrite
            )
        except ResourceNotFoundError as e:
            raise InvalidToolCallParameterException("source", f"source not found: {source}") from e
        except EtagMismatchError as e:
            raise InvalidToolCallParameterException(
                "destination",
                f"destination already exists: {dest_display}; pass overwrite=True to replace",
            ) from e
        except DialException as e:
            self._check_permission_denied(e, source, parameter_name="source")
            raise

        result = ToolCallResult(content=f"Moved to: {dest_display}", content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
