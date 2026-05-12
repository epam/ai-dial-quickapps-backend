import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

DialFilesToolName = Literal[
    "internal_file_list",
    "internal_file_read_lines",
    "internal_file_search",
    "internal_file_write",
    "internal_file_edit",
    "internal_file_delete",
    "internal_file_copy",
    "internal_file_move",
]

_TEMPLATE_TOKEN_RE = re.compile(r"\{([^{}]*)\}")
_ALLOWED_TEMPLATE_TOKENS = {"appdata"}


class DialFilesConfig(BaseModel):
    enabled_tools: Literal["all"] | list[DialFilesToolName] = Field(
        default="all",
        description=(
            "Which file tools to expose. Use 'all' for every tool, "
            "or a list to restrict (e.g. ['internal_file_read_lines', 'internal_file_search'])."
        ),
    )
    agent_home_dir: str = Field(
        default="files/{appdata}/",
        description=(
            "Base directory for relative path resolution. Must start with 'files/' and end with '/'. "
            "Supports the {appdata} template variable, resolved at request time via my_appdata_home(). "
            "Examples: 'files/{appdata}/' (default), 'files/shared-bucket/admin/', "
            "'files/{appdata}/workspace/'."
        ),
    )

    @field_validator("agent_home_dir")
    @classmethod
    def _validate_agent_home_dir(cls, value: str) -> str:
        if not value.startswith("files/"):
            raise ValueError("agent_home_dir must start with 'files/'")
        if not value.endswith("/"):
            raise ValueError("agent_home_dir must end with '/'")
        for segment in value.split("/"):
            if segment == "..":
                raise ValueError("agent_home_dir must not contain '..' segments")
        tokens = _TEMPLATE_TOKEN_RE.findall(value)
        if len(tokens) > 1:
            raise ValueError("agent_home_dir may contain at most one '{appdata}' placeholder")
        for token in tokens:
            if token not in _ALLOWED_TEMPLATE_TOKENS:
                raise ValueError(
                    f"agent_home_dir contains unknown template token '{{{token}}}'; "
                    f"allowed: {sorted(_ALLOWED_TEMPLATE_TOKENS)}"
                )
        return value
