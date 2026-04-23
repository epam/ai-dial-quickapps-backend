from aidial_sdk.chat_completion import Stage, Status
from injector import ProviderOf, inject

from quickapp.common.exceptions import (
    InitializationException,
    SkillCatastrophicInitializationException,
    SkillInitializationException,
    ToolInitializationException,
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
            exceptions = []

        if not exceptions:
            return

        tool_entries = [e for e in exceptions if isinstance(e, ToolInitializationException)]
        skill_entries = [e for e in exceptions if isinstance(e, SkillInitializationException)]

        markdown_lines: list[str] = []
        if tool_entries:
            markdown_lines.append("#### Tool initialization")
            for tool_exc in tool_entries:
                markdown_lines.append(
                    f"- **{tool_exc.tool_name}{tool_exc.toolset_name}**: {tool_exc}"
                )
                if tool_exc.details:
                    markdown_lines.append(f"```\n{tool_exc.details}\n```")

        if skill_entries:
            if tool_entries:
                markdown_lines.append("")
            markdown_lines.append("#### Skill loading")
            catastrophics = [
                e for e in skill_entries if isinstance(e, SkillCatastrophicInitializationException)
            ]
            per_url = [
                e
                for e in skill_entries
                if not isinstance(e, SkillCatastrophicInitializationException)
            ]
            if catastrophics:
                markdown_lines.append(
                    "> DIAL prompts as a whole could not be loaded — falling back to predefined skills only."
                )
                for catastrophic_exc in catastrophics:
                    markdown_lines.append(f"- {catastrophic_exc.reason}")
            for skill_exc in per_url:
                markdown_lines.append(f"- **{skill_exc.url}**: {skill_exc.reason}")

        status = Status.FAILED if any(e.is_hard for e in exceptions) else Status.COMPLETED
        stage = self.__stage_provider.get()
        stage.open()
        stage.append_name("Initialization issues")
        stage.append_content("\n".join(markdown_lines))
        stage.close(status)
