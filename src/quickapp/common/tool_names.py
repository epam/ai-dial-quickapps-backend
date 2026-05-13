"""Canonical OpenAI function names for internal QuickApp tools (sent to the LLM).

Keep this module free of heavy imports; other modules import names from here for
identity checks, wiring, and drift-sensitive tooling (see ``dump_internal_tools.py``).
"""

# Attachment processing / lazy context
INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME = "internal_attachments_available_context"
INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME = "internal_attachments_get_content"

# Skills
INTERNAL_SKILLS_READ_SKILL_TOOL_NAME = "internal_skills_read_skill"

# Timestamp
INTERNAL_TIMEAWARENESS_CURRENT_TIMESTAMP_TOOL_NAME = "internal_timeawareness_current_timestamp"

# Python code interpreter (internal tooling)
INTERNAL_CODE_EXECUTION_PYTHON_INTERPRETER_TOOL_NAME = "internal_code_execution_python_interpreter"
