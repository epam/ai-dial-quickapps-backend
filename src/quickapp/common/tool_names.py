"""Canonical OpenAI function names for internal QuickApp tools (sent to the LLM).

Kept free of heavy imports so it can be cited from identity checks anywhere in the tree
without pulling in DI or config.
"""

INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME = "internal_attachments_available_context"
INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME = "internal_attachments_get_content"
INTERNAL_SKILLS_READ_SKILL_TOOL_NAME = "internal_skills_read_skill"
INTERNAL_MCP_READ_RESOURCE_TOOL_NAME = "read_mcp_resource"
INTERNAL_TIMEAWARENESS_CURRENT_TIMESTAMP_TOOL_NAME = "internal_timeawareness_current_timestamp"
INTERNAL_CODE_EXECUTION_PYTHON_INTERPRETER_TOOL_NAME = "internal_code_execution_python_interpreter"
INTERNAL_WEB_FETCH_TOOL_NAME = "internal_web_fetch"
INTERNAL_REPRESENTATION_ADD_ATTACHMENT_TOOL_NAME = "internal_representation_add_attachment"

# DIAL files tools — all share the ``internal_file_`` prefix.
INTERNAL_FILE_TOOL_NAME_PREFIX = "internal_file_"
INTERNAL_FILE_LIST_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}list"
INTERNAL_FILE_READ_LINES_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}read_lines"
INTERNAL_FILE_SEARCH_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}search"
INTERNAL_FILE_FIND_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}find"
INTERNAL_FILE_WRITE_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}write"
INTERNAL_FILE_EDIT_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}edit"
INTERNAL_FILE_DELETE_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}delete"
INTERNAL_FILE_COPY_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}copy"
INTERNAL_FILE_MOVE_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}move"
