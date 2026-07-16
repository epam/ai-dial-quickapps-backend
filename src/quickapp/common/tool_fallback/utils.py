from quickapp.common.exceptions.tool_error import ToolErrorException


def compose_tool_error_fallback_message(
    *,
    instructions: str,
    error: Exception,
    forward_tool_error_message: bool,
) -> str:
    if forward_tool_error_message and isinstance(error, ToolErrorException):
        return f"{error.error_message}\n\n{instructions}"
    return instructions
