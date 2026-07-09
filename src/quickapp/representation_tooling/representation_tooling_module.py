import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider

from quickapp.common import StagedBaseTool
from quickapp.common.preview import preview_module
from quickapp.common.tool_names import INTERNAL_REPRESENTATION_ADD_ATTACHMENT_TOOL_NAME
from quickapp.config.application import ApplicationConfig
from quickapp.representation_tooling._add_attachment_tool import _AddAttachmentTool
from quickapp.representation_tooling._add_attachment_tool_config import ADD_ATTACHMENT_TOOL_CONFIG

logger = logging.getLogger(__name__)


@preview_module
class RepresentationToolingModule(Module):
    """Tools that control how the agent represents its work to the user (e.g. response attachments)."""

    def configure(self, binder: Binder) -> None:
        binder.bind(_AddAttachmentTool, to=_AddAttachmentTool, scope=request_scope)
        logger.debug("RepresentationTooling module configuration completed")

    @multiprovider
    def _provide_representation_tools(
        self,
        app_config: ApplicationConfig,
        builder: AssistedBuilder[_AddAttachmentTool],
    ) -> list[StagedBaseTool]:
        cfg = app_config.features.representation_tooling if app_config.features else None
        if cfg is None or not cfg.add_attachment:
            return []
        return [
            builder.build(
                tool_config=ADD_ATTACHMENT_TOOL_CONFIG,
                name=INTERNAL_REPRESENTATION_ADD_ATTACHMENT_TOOL_NAME,
                description=ADD_ATTACHMENT_TOOL_CONFIG.open_ai_tool.function.description,
            )
        ]
