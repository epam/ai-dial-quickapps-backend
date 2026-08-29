import logging

from aidial_sdk.chat_completion import Stage, Status
from injector import ProviderOf, inject

from quickapp.common.exceptions import (
    ConfigResolutionException,
    HookInitializationException,
    InitializationException,
    OffloadConfigurationException,
    SkillCatastrophicInitializationException,
    SkillInitializationException,
    ToolInitializationException,
)
from quickapp.common.utils import fenced_code_block

logger = logging.getLogger(__name__)

_STAGE_NAME = "Initialization issues"
_TOOL_SECTION = "#### Tool initialization"
_HOOK_SECTION = "#### Hook initialization"
_SKILL_SECTION = "#### Skill loading"
_OFFLOAD_SECTION = "#### Large tool-response offload"
# Source-neutral on purpose: this header renders for any skill source whose
# resolver failed as a whole, not just DIAL prompts.
_CATASTROPHIC_HEADER = (
    "> Configured skills could not be loaded — falling back to predefined skills only."
)
_PER_URL_ERRORS_HEADER = "> Errors:"
_PER_URL_WARNINGS_HEADER = "> Warnings:"


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
        hook_lines: list[str] = []
        catastrophic_lines: list[str] = []
        per_url_error_lines: list[str] = []
        per_url_warning_lines: list[str] = []
        offload_lines: list[str] = []
        for exc in exceptions:
            if isinstance(exc, ToolInitializationException):
                tool_lines.append(f"- **{exc.tool_name}{exc.toolset_name}**: {exc}")
                if exc.details:
                    tool_lines.append(fenced_code_block(exc.details))
            elif isinstance(exc, HookInitializationException):
                hook_lines.append(f"- **{exc.tool_name}{exc.toolset_name}**: {exc}")
                if exc.details:
                    hook_lines.append(fenced_code_block(exc.details))
            elif isinstance(exc, OffloadConfigurationException):
                offload_lines.append(f"- {exc}")
            elif isinstance(exc, ConfigResolutionException):
                tool_lines.append(f"- **template '{exc.template_name}'**: {exc}")
                if exc.details:
                    tool_lines.append(fenced_code_block(exc.details))
            elif isinstance(exc, SkillCatastrophicInitializationException):
                catastrophic_lines.append(f"- {exc.reason}")
            elif isinstance(exc, SkillInitializationException) and exc.url is not None:
                line = f"- **{exc.url}**: {exc.reason}"
                if exc.severity == "warning":
                    per_url_warning_lines.append(line)
                else:
                    per_url_error_lines.append(line)
            else:
                logger.warning(
                    "Unhandled InitializationException subclass %s; not rendered to stage",
                    type(exc).__name__,
                )

        sections: list[list[str]] = []
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

        status = Status.FAILED if any(exc.is_hard for exc in exceptions) else Status.COMPLETED
        stage = self.__stage_provider.get()
        stage.open()
        try:
            stage.append_name(_STAGE_NAME)
            stage.append_content("\n\n".join("\n".join(section) for section in sections))
        finally:
            stage.close(status)
