import logging
import re

import yaml
from aidial_client._exception import ResourceNotFoundError
from injector import inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.project_context import PROJECT_CONTEXT, ProjectContext
from quickapp.config.application import ApplicationConfig
from quickapp.dial_core_services.dial_file_service import DialFileService

logger = logging.getLogger(__name__)

# Caps keep a large PROJECT.md or context/ folder from crowding out the conversation.
MAX_INSTRUCTIONS_CHARS = 32_000
MAX_CONTEXT_ENTRIES = 100
# Recursion bound for listing context/; matches the file tools' max_depth ceiling.
_CONTEXT_LIST_DEPTH = 10

_FRONTMATTER_RE = re.compile(
    r"\A\ufeff?[ \t\r\n]*---[ \t\r]*\n(.*?)\n---[ \t\r]*(?:\n|\Z)", re.DOTALL
)


@inject
class _ProjectPromptProvider(PromptPartProvider):
    """Adds the project's instructions and files to the system prompt in a project chat.

    Registered right after the app's own system prompt; empty outside a project. "Project
    instructions" is the ``PROJECT.md`` body (frontmatter stripped, capped); "Project files"
    names the working folder and lists ``context/``, only when the app has the file tools to
    use them.
    """

    def __init__(
        self,
        project: PROJECT_CONTEXT,
        app_config: ApplicationConfig,
        dial_file_service: DialFileService,
    ) -> None:
        self.__project: PROJECT_CONTEXT = project
        self.__app_config = app_config
        self.__dial_file_service = dial_file_service

    async def get_prompt_part(self) -> str:
        project = self.__project
        if project is None:
            return ""
        sections = [await self.__instructions_section(project)]
        if self.__has_file_tools():
            sections.append(await self.__files_section(project))
        return "\n\n".join(section for section in sections if section)

    async def __instructions_section(self, project: ProjectContext) -> str:
        body = await self.__read_instructions(project)
        if not body:
            return ""
        note = ""
        if len(body) > MAX_INSTRUCTIONS_CHARS:
            note = (
                f"\n[Project instructions truncated: the first {MAX_INSTRUCTIONS_CHARS} "
                f"of {len(body)} characters are shown.]"
            )
            body = body[:MAX_INSTRUCTIONS_CHARS]
        return (
            "## Project instructions\n\n"
            "This chat is part of a project. The user wrote the instructions below for it. "
            "Treat them as user context: where they conflict with the instructions above, "
            "the instructions above win.\n\n"
            f"<project_instructions>\n{body}\n</project_instructions>{note}"
        )

    async def __read_instructions(self, project: ProjectContext) -> str:
        try:
            data, _ = await self.__dial_file_service.download_file(project.instructions_url)
        except ResourceNotFoundError:
            return ""
        return strip_frontmatter(data.decode("utf-8", errors="replace")).strip()

    async def __files_section(self, project: ProjectContext) -> str:
        lines = [
            "## Project files",
            "",
            f"Your working folder is the project's `{project.artifacts_root}`: relative "
            "paths resolve there, and it holds files from earlier chats in this project.",
        ]
        context_files = await self.__list_context_files(project)
        if context_files:
            lines += [
                "",
                "The project's context files, read-only (read them by their full path):",
                *(f"- {url}" for url in context_files[:MAX_CONTEXT_ENTRIES]),
            ]
            if len(context_files) > MAX_CONTEXT_ENTRIES:
                lines.append(f"- and {len(context_files) - MAX_CONTEXT_ENTRIES} more")
        return "\n".join(lines)

    async def __list_context_files(self, project: ProjectContext) -> list[str]:
        entries = await self.__dial_file_service.list_folder(
            project.context_root, max_depth=_CONTEXT_LIST_DEPTH
        )
        return sorted(entry.url for entry in entries if not entry.is_folder)

    def __has_file_tools(self) -> bool:
        features = self.__app_config.features
        return features is not None and features.dial_files is not None


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
