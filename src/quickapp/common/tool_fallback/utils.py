from quickapp.common.exceptions.tool_error import ToolErrorException


def extract_error_content(error: Exception) -> str:
    """Return the LLM-facing error string: ToolErrorException.error_message or str(error)."""
    if isinstance(error, ToolErrorException):
        return error.error_message
    return str(error)


def compose_fallback_content(error: Exception, instructions: str | None = None) -> str:
    content = extract_error_content(error)
    base = f"The tool call failed with an error: {content}" if content else "The tool call failed with an error."
    if instructions:
        return f"{base}\n\n{instructions}"
    return base
