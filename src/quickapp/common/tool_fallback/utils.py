from quickapp.common.exceptions.tool_error import ToolErrorException


def extract_error_content(error: Exception) -> str:
    """Return the LLM-facing error string: ToolErrorException.error_message or str(error)."""
    if isinstance(error, ToolErrorException):
        return error.error_message
    return str(error)
