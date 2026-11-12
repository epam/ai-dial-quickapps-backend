import logging

from fastapi_injector import request_scope
from injector import Binder, Module, multiprovider

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.shared.file_transfer._file_argument_transformer import _FileArgumentTransformer
from quickapp.shared.file_transfer._file_loader_service import FileLoaderService
from quickapp.shared.file_transfer.file_source import FileSource

logger = logging.getLogger(__name__)


class FileTransferModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_FileArgumentTransformer, to=_FileArgumentTransformer, scope=request_scope)
        binder.bind(FileLoaderService, to=FileLoaderService, scope=request_scope)

    @multiprovider
    def _provide_file_sources(self) -> list[FileSource]:
        """Declares the extension point so the list resolves when no feature contributes."""
        return []

    @multiprovider
    def _provide_argument_transformers(
        self,
        file_argument_transformer: _FileArgumentTransformer,
    ) -> list[ToolArgumentTransformer]:
        return [file_argument_transformer]
