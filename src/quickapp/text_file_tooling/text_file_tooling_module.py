import logging
from typing import Any

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider

from quickapp.common import StagedBaseTool
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.internal import InternalTool
from quickapp.text_file_tooling._delete_file_tool import _DeleteFileTool
from quickapp.text_file_tooling._edit_file_tool import _EditFileTool
from quickapp.text_file_tooling._read_file_lines_tool import _ReadFileLinesTool
from quickapp.text_file_tooling._search_in_file_tool import _SearchInFileTool
from quickapp.text_file_tooling._stage_wrapper import _FileStageWrapper
from quickapp.text_file_tooling._tool_configs import (
    DELETE_FILE_TOOL_CONFIG,
    EDIT_FILE_TOOL_CONFIG,
    READ_FILE_LINES_TOOL_CONFIG,
    SEARCH_IN_FILE_TOOL_CONFIG,
    WRITE_FILE_TOOL_CONFIG,
)
from quickapp.text_file_tooling._write_file_tool import _WriteFileTool

logger = logging.getLogger(__name__)


@preview_module
class TextFileToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_FileStageWrapper, to=_FileStageWrapper, scope=request_scope)
        binder.bind(_ReadFileLinesTool, to=_ReadFileLinesTool, scope=request_scope)
        binder.bind(_SearchInFileTool, to=_SearchInFileTool, scope=request_scope)
        binder.bind(_WriteFileTool, to=_WriteFileTool, scope=request_scope)
        binder.bind(_EditFileTool, to=_EditFileTool, scope=request_scope)
        binder.bind(_DeleteFileTool, to=_DeleteFileTool, scope=request_scope)
        logger.debug("TextFileToolingModule configuration completed")

    @multiprovider
    def _provide_text_file_tools(
        self,
        app_config: ApplicationConfig,
        read_builder: AssistedBuilder[_ReadFileLinesTool],
        search_builder: AssistedBuilder[_SearchInFileTool],
        write_builder: AssistedBuilder[_WriteFileTool],
        edit_builder: AssistedBuilder[_EditFileTool],
        delete_builder: AssistedBuilder[_DeleteFileTool],
    ) -> list[StagedBaseTool]:
        cfg = app_config.features.text_file_tools if app_config.features else None
        if cfg is None:
            return []

        tools: list[tuple[AssistedBuilder[Any], InternalTool]] = [
            (read_builder, READ_FILE_LINES_TOOL_CONFIG),
            (search_builder, SEARCH_IN_FILE_TOOL_CONFIG),
            (write_builder, WRITE_FILE_TOOL_CONFIG),
            (edit_builder, EDIT_FILE_TOOL_CONFIG),
            (delete_builder, DELETE_FILE_TOOL_CONFIG),
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
