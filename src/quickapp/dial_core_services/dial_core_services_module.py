import logging

from fastapi_injector import request_scope
from injector import Binder, Module, singleton

from quickapp.dial_core_services._interactive_login_service import InteractiveLoginService
from quickapp.dial_core_services._interactive_login_settings import InteractiveLoginSettings
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

logger = logging.getLogger(__name__)


class DialCoreServicesModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(ToolConfigCoreService, ToolConfigCoreService, scope=singleton)
        binder.bind(AttachmentService, AttachmentService, scope=request_scope)
        binder.bind(DialFileService, DialFileService, scope=request_scope)
        binder.bind(InteractiveLoginSettings, InteractiveLoginSettings, scope=singleton)
        binder.bind(InteractiveLoginService, InteractiveLoginService, scope=request_scope)
