import logging
from typing import Any

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider, provider

from quickapp.common import StagedBaseTool
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.config.dial_files import DialFilesConfig
from quickapp.config.tools.internal import InternalTool
from quickapp.dial_files_tooling._copy_file_tool import _CopyFileTool
from quickapp.dial_files_tooling._delete_file_tool import _DeleteFileTool
from quickapp.dial_files_tooling._edit_file_tool import _EditFileTool
from quickapp.dial_files_tooling._list_files_tool import _ListFilesTool
from quickapp.dial_files_tooling._move_file_tool import _MoveFileTool
from quickapp.dial_files_tooling._read_file_lines_tool import _ReadFileLinesTool
from quickapp.dial_files_tooling._search_in_file_tool import _SearchInFileTool
from quickapp.dial_files_tooling._stage_wrapper import _FileStageWrapper
from quickapp.dial_files_tooling._tool_configs import (
    COPY_FILE_TOOL_CONFIG,
    DELETE_FILE_TOOL_CONFIG,
    EDIT_FILE_TOOL_CONFIG,
    LIST_FILES_TOOL_CONFIG,
    MOVE_FILE_TOOL_CONFIG,
    READ_FILE_LINES_TOOL_CONFIG,
    SEARCH_IN_FILE_TOOL_CONFIG,
    WRITE_FILE_TOOL_CONFIG,
)
from quickapp.dial_files_tooling._write_file_tool import _WriteFileTool

logger = logging.getLogger(__name__)


@preview_module
class DialFilesToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_FileStageWrapper, to=_FileStageWrapper, scope=request_scope)
        binder.bind(_ListFilesTool, to=_ListFilesTool, scope=request_scope)
        binder.bind(_ReadFileLinesTool, to=_ReadFileLinesTool, scope=request_scope)
        binder.bind(_SearchInFileTool, to=_SearchInFileTool, scope=request_scope)
        binder.bind(_WriteFileTool, to=_WriteFileTool, scope=request_scope)
        binder.bind(_EditFileTool, to=_EditFileTool, scope=request_scope)
        binder.bind(_DeleteFileTool, to=_DeleteFileTool, scope=request_scope)
        binder.bind(_CopyFileTool, to=_CopyFileTool, scope=request_scope)
        binder.bind(_MoveFileTool, to=_MoveFileTool, scope=request_scope)
        logger.debug("DialFilesToolingModule configuration completed")

    @request_scope
    @provider
    def _provide_dial_files_config(self, app_config: ApplicationConfig) -> DialFilesConfig:
        cfg = app_config.features.dial_files if app_config.features else None
        if cfg is None:
            return DialFilesConfig()
        return cfg

    @multiprovider
    def _provide_dial_files_tools(
        self,
        app_config: ApplicationConfig,
        list_builder: AssistedBuilder[_ListFilesTool],
        read_builder: AssistedBuilder[_ReadFileLinesTool],
        search_builder: AssistedBuilder[_SearchInFileTool],
        write_builder: AssistedBuilder[_WriteFileTool],
        edit_builder: AssistedBuilder[_EditFileTool],
        delete_builder: AssistedBuilder[_DeleteFileTool],
        copy_builder: AssistedBuilder[_CopyFileTool],
        move_builder: AssistedBuilder[_MoveFileTool],
    ) -> list[StagedBaseTool]:
        cfg = app_config.features.dial_files if app_config.features else None
        if cfg is None:
            return []

        tools: list[tuple[AssistedBuilder[Any], InternalTool]] = [
            (list_builder, LIST_FILES_TOOL_CONFIG),
            (read_builder, READ_FILE_LINES_TOOL_CONFIG),
            (search_builder, SEARCH_IN_FILE_TOOL_CONFIG),
            (write_builder, WRITE_FILE_TOOL_CONFIG),
            (edit_builder, EDIT_FILE_TOOL_CONFIG),
            (delete_builder, DELETE_FILE_TOOL_CONFIG),
            (copy_builder, COPY_FILE_TOOL_CONFIG),
            (move_builder, MOVE_FILE_TOOL_CONFIG),
        ]

        return [
            builder.build(
                tool_config=config,
                name=config.open_ai_tool.function.name,
                description=config.open_ai_tool.function.description,
            )
            for builder, config in tools
            if cfg.enabled_tools == "all" or config.open_ai_tool.function.name in cfg.enabled_tools
        ]
