import logging

from fastapi_injector import request_scope
from injector import Binder, Module, multiprovider, singleton

from quickapp.common.abstract.tool_call_result_processor import ToolCallResultProcessor
from quickapp.common.preview import preview_module
from quickapp.tool_call_result_offload._large_response_processor import LargeResponseProcessor
from quickapp.tool_call_result_offload._settings import ToolCallResultOffloadSettings

logger = logging.getLogger(__name__)


@preview_module
class ToolCallResultOffloadModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(
            ToolCallResultOffloadSettings, to=ToolCallResultOffloadSettings, scope=singleton
        )
        binder.bind(LargeResponseProcessor, to=LargeResponseProcessor, scope=request_scope)
        logger.debug("ToolCallResultOffloadModule configuration completed")

    @multiprovider
    def _provide_processors(
        self,
        processor: LargeResponseProcessor,
    ) -> list[ToolCallResultProcessor]:
        return [processor]
