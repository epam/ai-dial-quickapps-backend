import logging
from typing import Any

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider, provider

from quickapp.common import StagedBaseTool
from quickapp.common.abstract.tool_call_result_processor import ToolCallResultProcessor
from quickapp.common.exceptions import InitializationException, OffloadConfigurationException
from quickapp.common.preview import preview_module
from quickapp.common.tool_names import (
    INTERNAL_FILE_READ_LINES_TOOL_NAME,
    INTERNAL_FILE_SEARCH_TOOL_NAME,
    INTERNAL_FILE_TOOL_NAME_PREFIX,
)
from quickapp.config.application import ApplicationConfig
from quickapp.config.dial_files import DialFilesConfig, resolve_enabled_dial_files_tools
from quickapp.config.tools.internal import InternalTool
from quickapp.shared.dial_files._copy_file_tool import _CopyFileTool
from quickapp.shared.dial_files._delete_file_tool import _DeleteFileTool
from quickapp.shared.dial_files._edit_file_tool import _EditFileTool
from quickapp.shared.dial_files._list_files_tool import _ListFilesTool
from quickapp.shared.dial_files._move_file_tool import _MoveFileTool
from quickapp.shared.dial_files._offload_config import ResolvedOffloadConfig
from quickapp.shared.dial_files._offload_processor import ToolCallResultOffloadProcessor
from quickapp.shared.dial_files._read_file_lines_tool import _ReadFileLinesTool
from quickapp.shared.dial_files._search_in_file_tool import _SearchInFileTool
from quickapp.shared.dial_files._stage_wrapper import _FileStageWrapper
from quickapp.shared.dial_files._tool_configs import (
    COPY_FILE_TOOL_CONFIG,
    DELETE_FILE_TOOL_CONFIG,
    EDIT_FILE_TOOL_CONFIG,
    LIST_FILES_TOOL_CONFIG,
    MOVE_FILE_TOOL_CONFIG,
    READ_FILE_LINES_TOOL_CONFIG,
    SEARCH_IN_FILE_TOOL_CONFIG,
    WRITE_FILE_TOOL_CONFIG,
)
from quickapp.shared.dial_files._write_file_tool import _WriteFileTool

logger = logging.getLogger(__name__)


@preview_module
class DialFilesModule(Module):

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
        binder.bind(
            ToolCallResultOffloadProcessor,
            to=ToolCallResultOffloadProcessor,
            scope=request_scope,
        )
        logger.debug("DialFilesModule configuration completed")

    # Read-back tools (short names in DialFilesConfig.enabled_tools) the offload
    # notice points the LLM at. Offloading is useless without them.
    _REQUIRED_READ_BACK_TOOLS = frozenset({"read_lines", "search"})

    # The same two read-back tools in full (LLM-facing) name form. Always excluded
    # from offload, regardless of config: a large read-back slice must never be
    # re-offloaded (infinite recursion). This guard cannot be removed via the
    # per-app / env-var `excluded_tools`, which is additive on top of it.
    _MANDATORY_EXCLUDED_TOOLS = frozenset(
        {INTERNAL_FILE_READ_LINES_TOOL_NAME, INTERNAL_FILE_SEARCH_TOOL_NAME}
    )

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

        enabled = resolve_enabled_dial_files_tools(cfg.enabled_tools)

        def _is_enabled(config: InternalTool) -> bool:
            short_name = config.open_ai_tool.function.name.removeprefix(
                INTERNAL_FILE_TOOL_NAME_PREFIX
            )
            return short_name in enabled

        return [
            builder.build(
                tool_config=config,
                name=config.open_ai_tool.function.name,
                description=config.open_ai_tool.function.description,
            )
            for builder, config in tools
            if _is_enabled(config)
        ]

    @request_scope
    @provider
    def _provide_offload_config(self, app_config: ApplicationConfig) -> ResolvedOffloadConfig:
        # Offload is a dial-files sub-feature: it only exists when the feature is
        # configured. Checks the actual config — not the defaulted DialFilesConfig()
        # — so an absent feature can never re-enable offload.
        cfg = app_config.features.dial_files if app_config.features else None
        if cfg is None:
            # No dial-files: the feature was never requested.
            return ResolvedOffloadConfig(
                enabled=False, size_threshold=0, excluded_tools=frozenset()
            )
        offload = cfg.tool_call_result_offload
        if not offload.enabled:
            # Operator explicitly turned offload off: stay inline, no warning.
            return ResolvedOffloadConfig(
                enabled=False, size_threshold=0, excluded_tools=frozenset()
            )

        # Hard dependency on the read-back tools: disable offload when they are
        # not exposed, so the LLM is never handed a pointer it cannot follow. The
        # missing tools are carried on the resolved config so the warning provider
        # can reuse this single resolution instead of re-deriving it.
        missing = self._missing_read_back_tools(cfg)
        return ResolvedOffloadConfig(
            enabled=not missing,
            size_threshold=offload.size_threshold,
            excluded_tools=frozenset(offload.excluded_tools) | self._MANDATORY_EXCLUDED_TOOLS,
            missing_read_back_tools=tuple(missing),
        )

    @multiprovider
    def _provide_offload_processors(
        self,
        processor: ToolCallResultOffloadProcessor,
    ) -> list[ToolCallResultProcessor]:
        return [processor]

    @multiprovider
    def _provide_initialization_exceptions(
        self,
        offload_config: ResolvedOffloadConfig,
    ) -> list[InitializationException]:
        # Warn (not fail) when offload was requested but its read-back tools are
        # not exposed. missing_read_back_tools is empty when offload was never
        # requested or is fully satisfied, so there is nothing to warn about.
        if not offload_config.missing_read_back_tools:
            return []
        return [
            OffloadConfigurationException(
                missing_tools=list(offload_config.missing_read_back_tools)
            )
        ]

    def _missing_read_back_tools(self, cfg: DialFilesConfig) -> list[str]:
        enabled = resolve_enabled_dial_files_tools(cfg.enabled_tools)
        return sorted(self._REQUIRED_READ_BACK_TOOLS - enabled)
