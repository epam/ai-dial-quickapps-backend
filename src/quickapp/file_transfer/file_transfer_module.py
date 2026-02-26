import logging

from fastapi_injector import request_scope
from injector import Binder, Module, multiprovider

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.file_transfer._file_argument_transformer import _FileArgumentTransformer
from quickapp.file_transfer._inject_file_transfer_instruction_transformer import (
    _InjectFileTransferInstructionTransformer,
)

logger = logging.getLogger(__name__)


class FileTransferModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_FileArgumentTransformer, to=_FileArgumentTransformer, scope=request_scope)
        binder.bind(
            _InjectFileTransferInstructionTransformer,
            to=_InjectFileTransferInstructionTransformer,
            scope=request_scope,
        )

    @multiprovider
    def _provide_argument_transformers(
        self,
        file_argument_transformer: _FileArgumentTransformer,
    ) -> list[ToolArgumentTransformer]:
        return [file_argument_transformer]

    @multiprovider
    def _provide_message_transformers(
        self,
        file_transfer_transformer: _InjectFileTransferInstructionTransformer,
    ) -> list[MessagesTransformer]:
        return [file_transfer_transformer]
