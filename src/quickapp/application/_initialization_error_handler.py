import logging

from aidial_sdk.chat_completion import Stage, Status
from injector import ProviderOf, inject

from quickapp.common.exceptions import (
    InitializationException,
    SkillCatastrophicInitializationException,
    SkillInitializationException,
    ToolInitializationException,
)

logger = logging.getLogger(__name__)

_STAGE_NAME = "Initialization issues"
_TOOL_SECTION = "#### Tool initialization"
_SKILL_SECTION = "#### Skill loading"
_CATASTROPHIC_HEADER = (
    "> DIAL prompts as a whole could not be loaded — falling back to predefined skills only."
)


@inject
class _InitializationErrorHandler:
    def __init__(
        self,
        stage_provider: ProviderOf[Stage],
        initialization_exceptions_provider: ProviderOf[list[InitializationException]],
    ):
        self.__initialization_exceptions_provider = initialization_exceptions_provider
        self.__stage_provider = stage_provider

    def handle_initialization_issues(self) -> None:
        try:
            exceptions = self.__initialization_exceptions_provider.get()
        except Exception:
            logger.warning(
                "Initialization exceptions provider failed; skipping stage render",
                exc_info=True,
            )
            exceptions = []

        if not exceptions:
            return

        tool_lines: list[str] = []
        catastrophic_lines: list[str] = []
        per_url_lines: list[str] = []
        for exc in exceptions:
            if isinstance(exc, ToolInitializationException):
                tool_lines.append(f"- **{exc.tool_name}{exc.toolset_name}**: {exc}")
                if exc.details:
                    tool_lines.append(f"```\n{exc.details}\n```")
            elif isinstance(exc, SkillCatastrophicInitializationException):
                catastrophic_lines.append(f"- {exc.reason}")
            elif isinstance(exc, SkillInitializationException) and exc.url is not None:
                per_url_lines.append(f"- **{exc.url}**: {exc.reason}")
            else:
                logger.warning(
                    "Unhandled InitializationException subclass %s; not rendered to stage",
                    type(exc).__name__,
                )

        sections: list[list[str]] = []
        if tool_lines:
            sections.append([_TOOL_SECTION, *tool_lines])
        if catastrophic_lines or per_url_lines:
            skill_section = [_SKILL_SECTION]
            if catastrophic_lines:
                skill_section.append(_CATASTROPHIC_HEADER)
                skill_section.extend(catastrophic_lines)
            skill_section.extend(per_url_lines)
            sections.append(skill_section)

        status = Status.FAILED if any(exc.is_hard for exc in exceptions) else Status.COMPLETED
        stage = self.__stage_provider.get()
        stage.open()
        try:
            stage.append_name(_STAGE_NAME)
            stage.append_content("\n\n".join("\n".join(section) for section in sections))
        finally:
            stage.close(status)
