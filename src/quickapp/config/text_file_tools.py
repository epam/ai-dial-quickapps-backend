from typing import Literal

from pydantic import BaseModel, Field

TextFileToolName = Literal[
    "read_file_lines", "search_in_file", "write_file", "edit_file", "delete_file"
]


class TextFileToolsConfig(BaseModel):
    enabled_tools: Literal["all"] | list[TextFileToolName] = Field(
        default="all",
        description=(
            "Which file tools to expose. Use 'all' for every tool, "
            "or a list to restrict (e.g. ['read_file_lines', 'search_in_file'])."
        ),
    )
