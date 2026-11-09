import logging

from aidial_client import DialException, ResourceNotFoundError
from aidial_sdk.exceptions import HTTPException as DialHTTPException
from injector import inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.project_context import PROJECT_CONTEXT
from quickapp.dial_core_services._project_files import ProjectFilesClient

logger = logging.getLogger(__name__)

PROJECT_ACCESS_DENIED_CODE = "project_access_denied"
PROJECT_NOT_FOUND_CODE = "project_not_found"

_MSG_ACCESS_DENIED = (
    "An administrator must approve the app's access to projects (resource dependencies)."
)
_MSG_NOT_FOUND = "The project was not found. It may have been deleted or renamed."


@inject
class _ProjectAccessPreflight(CompletionInitializer):
    """Checks once per request that the app can reach the request's project.

    One ``GET /v2/metadata/projects/{b}/{p}`` with the per-request key. Without access the
    turn fails here, before MCP connects, skill fetches or any LLM call, with an error that
    names the fix. Runs before ``_DialAppResolver`` (order -100).
    """

    order = -200

    def __init__(self, project: PROJECT_CONTEXT, project_files: ProjectFilesClient) -> None:
        self.__project: PROJECT_CONTEXT = project
        self.__project_files: ProjectFilesClient = project_files

    async def initialize(self) -> None:
        if self.__project is None:
            return
        try:
            await self.__project_files.project_metadata(self.__project.url)
        except ResourceNotFoundError as e:
            raise _client_error(404, PROJECT_NOT_FOUND_CODE, _MSG_NOT_FOUND) from e
        except DialException as e:
            if e.status_code == 403:
                raise _client_error(403, PROJECT_ACCESS_DENIED_CODE, _MSG_ACCESS_DENIED) from e
            raise
        logger.debug("Project access preflight passed")


def _client_error(status_code: int, code: str, message: str) -> DialHTTPException:
    return DialHTTPException(
        message=message,
        status_code=status_code,
        type="invalid_request_error",
        code=code,
        display_message=message,
    )
