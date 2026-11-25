from quickapp.common.utils import fenced_code_block

from .initialization import InitializationException


class ConfigResolutionException(InitializationException):
    """Raised when a predefined template's override patch fails to merge or validate."""

    def __init__(
        self,
        message: str,
        template_name: str,
        json_path: str = "",
        details: str = "",
    ):
        formatted = f"Config Resolution Error: {message} for template '{template_name}'"
        if json_path:
            formatted += f" at '{json_path}'"
        super().__init__(formatted)
        self.message = message
        self.template_name = template_name
        self.json_path = json_path
        self.details = details

    @property
    def user_facing_message(self) -> str:
        message = f"**template '{self.template_name}'**: {self}"
        return f"{message}\n{fenced_code_block(self.details)}" if self.details else message
