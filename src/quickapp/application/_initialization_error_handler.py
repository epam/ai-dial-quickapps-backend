from aidial_sdk.chat_completion import Stage, Status
from injector import ProviderOf, inject

from quickapp.common.exceptions import ToolInitializationException


@inject
class _InitializationErrorHandler:
    def __init__(
        self,
        stage_provider: ProviderOf[Stage],
        initialization_exceptions_provider: ProviderOf[list[ToolInitializationException]],
    ):
        self.__initialization_exceptions_provider = initialization_exceptions_provider
        self.__stage_provider = stage_provider

    def handle_initialization_errors(self) -> None:
        try:
            exceptions_list = self.__initialization_exceptions_provider.get()
        except Exception:
            exceptions_list = None

        if not exceptions_list:
            return
        stage = self.__stage_provider.get()
        stage.open()
        stage.append_name("🚨 Tool initialization errors 🚨")
        markdown_lines = ["#### The following errors occurred during tools initialization:"]
        for exc in exceptions_list:
            markdown_lines.append(f"- **{exc.tool_name}{exc.toolset_name}**: {exc}")
            if getattr(exc, "details", None):
                markdown_lines.append(f"```\n{exc.details}\n```")
            markdown_lines.append("---")
        markdown = "\n".join(markdown_lines)
        stage.append_content(markdown)
        stage.close(Status.FAILED)  # Mark the stage as failed just for UI purposes
