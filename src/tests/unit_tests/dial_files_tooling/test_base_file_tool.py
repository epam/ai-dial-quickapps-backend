from unittest.mock import AsyncMock

import pytest
from aidial_client._exception import DialException

from quickapp.config.application import StageDisplayLevel
from quickapp.dial_files_tooling._exceptions import DialFilePermissionException
from tests.unit_tests.dial_files_tooling._helpers import make_service, make_tool

# Home-resolution / display-path / path-validation logic lives in
# `HomePathResolver` (shared/home_path) and `_utils`, and is covered by
# tests/unit_tests/shared/test_home_path_resolver.py. This module covers
# tool-level behaviour built on top of them.


class TestPermissionDeniedWrapper:
    @pytest.mark.asyncio
    async def test_403_from_list_folder_raises_permission_exception(self):
        from quickapp.dial_files_tooling._list_files_tool import _ListFilesTool
        from quickapp.dial_files_tooling._tool_configs import LIST_FILES_TOOL_CONFIG

        service = make_service()
        service.list_folder = AsyncMock(
            side_effect=DialException(message="forbidden", status_code=403)
        )
        tool = make_tool(_ListFilesTool, LIST_FILES_TOOL_CONFIG, service=service)
        with pytest.raises(DialFilePermissionException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/")
        assert "access denied: reports/" in str(exc.value)

    @pytest.mark.asyncio
    async def test_403_goes_through_fallback_not_retry(self):
        """The model gets the fallback (continue) result, not "try to call the tool again"."""
        from quickapp.dial_files_tooling._read_file_lines_tool import _ReadFileLinesTool
        from quickapp.dial_files_tooling._tool_configs import READ_FILE_LINES_TOOL_CONFIG

        service = make_service()
        service.download_file = AsyncMock(
            side_effect=DialException(message="forbidden", status_code=403)
        )
        tool = make_tool(_ReadFileLinesTool, READ_FILE_LINES_TOOL_CONFIG, service=service)
        result = await tool.arun(
            "call-1", stage_level=StageDisplayLevel.NONE, path="notes.md", start_line=1, end_line=10
        )
        assert "access denied: notes.md" in result.content
        assert "try to call the tool again" not in result.content

    @pytest.mark.asyncio
    async def test_non_403_dial_exception_propagates(self):
        from quickapp.dial_files_tooling._list_files_tool import _ListFilesTool
        from quickapp.dial_files_tooling._tool_configs import LIST_FILES_TOOL_CONFIG

        service = make_service()
        service.list_folder = AsyncMock(
            side_effect=DialException(message="server error", status_code=500)
        )
        tool = make_tool(_ListFilesTool, LIST_FILES_TOOL_CONFIG, service=service)
        with pytest.raises(DialException):
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/")
