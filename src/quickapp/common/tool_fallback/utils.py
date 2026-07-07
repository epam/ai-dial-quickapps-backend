from ..exceptions.tool_error import ToolErrorException


def compose_tool_error_fallback_message(
    *,
    instructions: str | None,
    error: Exception,
    forward_tool_error_message: bool,
) -> str:
    error_message = ""
    if forward_tool_error_message and isinstance(error, ToolErrorException):
        error_message = error.error_message

    if instructions and error_message:
        return f"{error_message}\n\n{instructions}"
    if instructions:
        return instructions
    if error_message:
        return error_message
    return ""