from typing import Literal

from pydantic import BaseModel, Field

TextFileToolName = Literal[
    "internal_text_file_read_lines",
    "internal_text_file_search",
    "internal_text_file_write",
    "internal_text_file_edit",
    "internal_text_file_delete",
]


class TextFileToolsConfig(BaseModel):
    enabled_tools: Literal["all"] | list[TextFileToolName] = Field(
        default="all",
        description=(
            "Which file tools to expose. Use 'all' for every tool, "
            "or a list to restrict (e.g. ['internal_text_file_read_lines', 'internal_text_file_search'])."
        ),
    )
