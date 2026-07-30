from unittest.mock import AsyncMock

import pytest
from aidial_client._exception import DialException

from quickapp.common.exceptions import InvalidToolCallParameterException
from tests.unit_tests.dial_files_tooling._helpers import make_service, make_tool

# Home-resolution / display-path / path-validation logic lives in
# `HomePathResolver` (shared/home_path) and `_utils`, and is covered by
# tests/unit_tests/shared/test_home_path_resolver.py. This module covers
# tool-level behaviour built on top of them.


class TestPermissionDeniedWrapper:
    @pytest.mark.asyncio
    async def test_403_from_list_folder_converted_to_invalid_parameter(self):
        from quickapp.dial_files_tooling._list_files_tool import _ListFilesTool
        from quickapp.dial_files_tooling._tool_configs import LIST_FILES_TOOL_CONFIG

        service = make_service()
        service.list_folder = AsyncMock(
            side_effect=DialException(message="forbidden", status_code=403)
        )
        tool = make_tool(_ListFilesTool, LIST_FILES_TOOL_CONFIG, service=service)
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/")
        assert exc.value.parameter_name == "path"
        assert "access denied" in exc.value.message
        assert "reports/" in exc.value.message

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
