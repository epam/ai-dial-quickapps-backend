import logging

from aidial_sdk.chat_completion import Stage, Status
from injector import ProviderOf, inject

from quickapp.common.exceptions import (
    ConfigResolutionException,
    HookInitializationException,
    InitializationException,
    InitializationIssueLevel,
    OffloadConfigurationException,
    OrchestratorSystemPromptException,
    ProjectInstructionsException,
    SkillCatastrophicInitializationException,
    SkillInitializationException,
    ToolInitializationException,
)
from quickapp.common.utils import fenced_code_block

logger = logging.getLogger(__name__)

_STAGE_NAME = "Initialization issues"
_SYSTEM_PROMPT_SECTION = "#### System prompt"
_TOOL_SECTION = "#### Tool initialization"
_HOOK_SECTION = "#### Hook initialization"
_SKILL_SECTION = "#### Skill loading"
_OFFLOAD_SECTION = "#### Large tool-response offload"
_PROJECT_SECTION = "#### Project instructions"
_CATASTROPHIC_HEADER = (
    "> DIAL prompts as a whole could not be loaded — falling back to predefined skills only."
)
_PER_URL_ERRORS_HEADER = "> Errors:"
_PER_URL_WARNINGS_HEADER = "> Warnings:"
_LEVEL_ORDER = {
    InitializationIssueLevel.WARNING: 0,
    InitializationIssueLevel.ERROR: 1,
    InitializationIssueLevel.CRITICAL: 2,
}


def _lines_of(exc: InitializationException) -> list[str]:
    lines = [f"- {exc.user_facing_message}"]
    if exc.details:
        lines.append(fenced_code_block(exc.details))
    return lines


@inject
class _InitializationErrorHandler:
    def __init__(
        self,
        stage_provider: ProviderOf[Stage],
        initialization_exceptions_provider: ProviderOf[list[InitializationException]],
        level_provider: ProviderOf[InitializationIssueLevel],
    ):
        self.__initialization_exceptions_provider = initialization_exceptions_provider
        self.__stage_provider = stage_provider
        self.__level_provider = level_provider

    def handle_initialization_issues(self) -> None:
        try:
            exceptions = self.__initialization_exceptions_provider.get()
        except Exception:
            logger.warning(
                "Initialization exceptions provider failed; skipping stage render",
                exc_info=True,
            )
            exceptions = []

        exceptions = self.__filter_by_level(exceptions)
        if not exceptions:
            return

        system_prompt_lines: list[str] = []
        tool_lines: list[str] = []
        hook_lines: list[str] = []
        catastrophic_lines: list[str] = []
        per_url_error_lines: list[str] = []
        per_url_warning_lines: list[str] = []
        offload_lines: list[str] = []
        project_lines: list[str] = []
        for exc in exceptions:
            if isinstance(exc, OrchestratorSystemPromptException):
                system_prompt_lines.extend(_lines_of(exc))
            elif isinstance(exc, (ToolInitializationException, ConfigResolutionException)):
                tool_lines.extend(_lines_of(exc))
            elif isinstance(exc, HookInitializationException):
                hook_lines.extend(_lines_of(exc))
            elif isinstance(exc, OffloadConfigurationException):
                offload_lines.extend(_lines_of(exc))
            elif isinstance(exc, ProjectInstructionsException):
                project_lines.extend(_lines_of(exc))
            elif isinstance(exc, SkillCatastrophicInitializationException):
                catastrophic_lines.extend(_lines_of(exc))
            elif isinstance(exc, SkillInitializationException):
                if exc.level == InitializationIssueLevel.WARNING:
                    per_url_warning_lines.extend(_lines_of(exc))
                else:
                    per_url_error_lines.extend(_lines_of(exc))
            else:
                logger.warning(
                    "Unhandled InitializationException subclass %s; not rendered to stage",
                    type(exc).__name__,
                )

        sections: list[list[str]] = []
        if system_prompt_lines:
            sections.append([_SYSTEM_PROMPT_SECTION, *system_prompt_lines])
        if tool_lines:
            sections.append([_TOOL_SECTION, *tool_lines])
        if hook_lines:
            sections.append([_HOOK_SECTION, *hook_lines])
        if catastrophic_lines or per_url_error_lines or per_url_warning_lines:
            skill_section = [_SKILL_SECTION]
            if catastrophic_lines:
                skill_section.append(_CATASTROPHIC_HEADER)
                skill_section.extend(catastrophic_lines)
            if per_url_error_lines:
                skill_section.append(_PER_URL_ERRORS_HEADER)
                skill_section.extend(per_url_error_lines)
            if per_url_warning_lines:
                skill_section.append(_PER_URL_WARNINGS_HEADER)
                skill_section.extend(per_url_warning_lines)
            sections.append(skill_section)
        if offload_lines:
            sections.append([_OFFLOAD_SECTION, *offload_lines])
        if project_lines:
            sections.append([_PROJECT_SECTION, *project_lines])

        status = (
            Status.FAILED
            if any(exc.level == InitializationIssueLevel.CRITICAL for exc in exceptions)
            else Status.COMPLETED
        )
        stage = self.__stage_provider.get()
        stage.open()
        try:
            stage.append_name(_STAGE_NAME)
            stage.append_content("\n\n".join("\n".join(section) for section in sections))
        finally:
            stage.close(status)

    def __filter_by_level(
        self, exceptions: list[InitializationException]
    ) -> list[InitializationException]:
        if not exceptions:
            return exceptions
        level = self.__level_provider.get()
        shown: list[InitializationException] = []
        for exc in exceptions:
            if _LEVEL_ORDER[exc.level] >= _LEVEL_ORDER[level]:
                shown.append(exc)
            else:
                logger.info(
                    "Initialization issue hidden below level '%s': %s (%s) %s",
                    level.value,
                    type(exc).__name__,
                    exc.level.value,
                    exc,
                )
        return shown
