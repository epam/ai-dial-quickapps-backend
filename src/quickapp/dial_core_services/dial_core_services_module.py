import logging

from fastapi_injector import request_scope
from injector import Binder, Module, provider, singleton

from quickapp.common.abstract.folder_listing_provider import FolderListingProvider
from quickapp.common.project_context import PROJECT_CONTEXT
from quickapp.dial_core_services._folder_listing_provider import DialFolderListingProvider
from quickapp.dial_core_services._interactive_login_service import InteractiveLoginService
from quickapp.dial_core_services._interactive_login_settings import InteractiveLoginSettings
from quickapp.dial_core_services._project_files import ProjectFilesClient
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.deployment_names_service import DeploymentNamesCoreService
from quickapp.dial_core_services.dial_downloader import DialDownloader
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_core_services.storage._project_file_storage import ProjectFileStorage
from quickapp.dial_core_services.storage._routed_file_storage import RoutedFileStorage
from quickapp.dial_core_services.storage._v1_file_storage import V1FileStorage
from quickapp.dial_core_services.storage.file_storage import FileStorage
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

logger = logging.getLogger(__name__)


class DialCoreServicesModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(ToolConfigCoreService, ToolConfigCoreService, scope=singleton)
        binder.bind(DeploymentNamesCoreService, DeploymentNamesCoreService, scope=singleton)
        binder.bind(AttachmentService, AttachmentService, scope=request_scope)
        binder.bind(ProjectFilesClient, ProjectFilesClient, scope=request_scope)
        binder.bind(V1FileStorage, V1FileStorage, scope=request_scope)
        binder.bind(ProjectFileStorage, ProjectFileStorage, scope=request_scope)
        binder.bind(DialFileService, DialFileService, scope=request_scope)
        binder.bind(DialDownloader, DialDownloader, scope=request_scope)
        binder.bind(DialFilePromoter, DialFilePromoter, scope=request_scope)
        binder.bind(InteractiveLoginSettings, InteractiveLoginSettings, scope=singleton)
        binder.bind(InteractiveLoginService, InteractiveLoginService, scope=request_scope)
        binder.bind(
            FolderListingProvider,  # type: ignore[type-abstract]
            to=DialFolderListingProvider,
            scope=request_scope,
        )

    @provider
    @request_scope
    def __provide_file_storage(
        self,
        v1: V1FileStorage,
        project_storage: ProjectFileStorage,
        project: PROJECT_CONTEXT,
    ) -> FileStorage:
        """v1 only, unless the request has a project: then URLs of that project go to v2."""
        if project is None:
            return v1
        return RoutedFileStorage(v1, project_storage, project)
