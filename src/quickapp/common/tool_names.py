"""Canonical OpenAI function names for internal QuickApp tools (sent to the LLM).

Kept free of heavy imports so it can be cited from identity checks anywhere in the tree
without pulling in DI or config.
"""

# Attachment processing
INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME = "internal_attachments_available_context"

# Skills
INTERNAL_SKILLS_READ_SKILL_TOOL_NAME = "internal_skills_read_skill"

# Timestamp
INTERNAL_TIMEAWARENESS_CURRENT_TIMESTAMP_TOOL_NAME = "internal_timeawareness_current_timestamp"

# Python code interpreter (internal tooling)
INTERNAL_CODE_EXECUTION_PYTHON_INTERPRETER_TOOL_NAME = "internal_code_execution_python_interpreter"
