import logging
import re

import yaml
from aidial_client import DialException, ResourceNotFoundError
from injector import inject

from quickapp.common.exceptions import InitializationException, ProjectInstructionsException
from quickapp.common.project_context import PROJECT_CONTEXT
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_core_services.exceptions import FileTooLargeError

logger = logging.getLogger(__name__)

# The frontmatter body is optional (lazily), so an empty `---\n---` block is stripped too.
_FRONTMATTER_RE = re.compile(
    r"\A﻿?[ \t\r\n]*---[ \t\r]*\n(?:(.*?)\n)??---[ \t\r]*(?:\n|\Z)", re.DOTALL
)


@inject
class _ProjectInstructions:
    """The request project's ``PROJECT.md`` body, loaded once per request.

    Loaded by the access preflight, so a failure reaches the user as a warning in the
    Initialization issues stage before the turn; the prompt provider then reads the same
    result. A missing file is no instructions, not an issue.
    """

    def __init__(self, project: PROJECT_CONTEXT, dial_file_service: DialFileService) -> None:
        self.__project: PROJECT_CONTEXT = project
        self.__dial_file_service = dial_file_service
        self.__body: str | None = None
        self.__exceptions: list[InitializationException] = []

    @property
    def exceptions(self) -> list[InitializationException]:
        return self.__exceptions

    async def body(self) -> str:
        """The body without frontmatter, stripped; ``""`` outside a project, for a missing
        or empty file, or when it couldn't be loaded."""
        if self.__body is None:
            self.__body = await self.__load()
        return self.__body

    async def __load(self) -> str:
        if self.__project is None:
            return ""
        try:
            data, _ = await self.__dial_file_service.download_file(self.__project.instructions_url)
        except ResourceNotFoundError:
            return ""
        except (FileTooLargeError, DialException) as e:
            reason = _describe_read_error(e)
            logger.warning("Skipping the project instructions: PROJECT.md not loaded (%s)", reason)
            self.__exceptions.append(ProjectInstructionsException(reason))
            return ""
        return strip_frontmatter(data.decode("utf-8", errors="replace")).strip()


def _describe_read_error(error: Exception) -> str:
    """A short, payload-free reason for the stage and the log."""
    if isinstance(error, FileTooLargeError):
        return f"larger than the {error.limit}-byte limit"
    if isinstance(error, DialException):
        return f"DIAL Core returned {error.status_code}"
    return type(error).__name__


def strip_frontmatter(content: str) -> str:
    """``content`` without its leading YAML frontmatter.

    Malformed frontmatter (unterminated, unparseable or not a mapping) is not stripped: the
    whole file is the body.
    """
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        return content
    try:
        parsed = yaml.safe_load(match.group(1) or "")
    except yaml.YAMLError:
        return content
    if parsed is not None and not isinstance(parsed, dict):
        return content
    return content[match.end() :]
