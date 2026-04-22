import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider

from quickapp.common.preview import preview_module
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.text_file_tooling._read_file_lines_tool import _ReadFileLinesTool
from quickapp.text_file_tooling._search_in_file_tool import _SearchInFileTool
from quickapp.text_file_tooling._stage_wrapper import _TextFileStageWrapper
from quickapp.text_file_tooling._tool_configs import (
    READ_FILE_LINES_TOOL_CONFIG,
    READ_FILE_LINES_TOOL_NAME,
    SEARCH_IN_FILE_TOOL_CONFIG,
    SEARCH_IN_FILE_TOOL_NAME,
)

logger = logging.getLogger(__name__)


@preview_module
class TextFileToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_TextFileStageWrapper, to=_TextFileStageWrapper, scope=request_scope)
        binder.bind(_ReadFileLinesTool, to=_ReadFileLinesTool, scope=request_scope)
        binder.bind(_SearchInFileTool, to=_SearchInFileTool, scope=request_scope)
        logger.debug("TextFileToolingModule configuration completed")

    @multiprovider
    def _provide_text_file_tools(
        self,
        read_lines_builder: AssistedBuilder[_ReadFileLinesTool],
        search_builder: AssistedBuilder[_SearchInFileTool],
    ) -> list[StagedBaseTool]:
        return [
            read_lines_builder.build(
                tool_config=READ_FILE_LINES_TOOL_CONFIG,
                name=READ_FILE_LINES_TOOL_NAME,
                description=READ_FILE_LINES_TOOL_CONFIG.open_ai_tool.function.description,
            ),
            search_builder.build(
                tool_config=SEARCH_IN_FILE_TOOL_CONFIG,
                name=SEARCH_IN_FILE_TOOL_NAME,
                description=SEARCH_IN_FILE_TOOL_CONFIG.open_ai_tool.function.description,
            ),
        ]
