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

        tools: list[ToolInitializationException] = []
        catastrophics: list[SkillCatastrophicInitializationException] = []
        per_url_skills: list[SkillInitializationException] = []
        for exc in exceptions:
            if isinstance(exc, ToolInitializationException):
                tools.append(exc)
            elif isinstance(exc, SkillCatastrophicInitializationException):
                catastrophics.append(exc)
            elif isinstance(exc, SkillInitializationException) and exc.url is not None:
                per_url_skills.append(exc)
            else:
                logger.warning(
                    "Unhandled InitializationException subclass %s; not rendered to stage",
                    type(exc).__name__,
                )

        sections: list[list[str]] = []
        if tools:
            section = [_TOOL_SECTION]
            for tool_exc in tools:
                section.append(f"- **{tool_exc.tool_name}{tool_exc.toolset_name}**: {tool_exc}")
                if tool_exc.details:
                    section.append(f"```\n{tool_exc.details}\n```")
            sections.append(section)

        if catastrophics or per_url_skills:
            section = [_SKILL_SECTION]
            if catastrophics:
                section.append(_CATASTROPHIC_HEADER)
                for catastrophic_exc in catastrophics:
                    section.append(f"- {catastrophic_exc.reason}")
            for skill_exc in per_url_skills:
                section.append(f"- **{skill_exc.url}**: {skill_exc.reason}")
            sections.append(section)

        status = Status.FAILED if any(exc.is_hard for exc in exceptions) else Status.COMPLETED
        stage = self.__stage_provider.get()
        stage.open()
        try:
            stage.append_name(_STAGE_NAME)
            stage.append_content("\n\n".join("\n".join(section) for section in sections))
        finally:
            stage.close(status)
