from typing import Literal

from pydantic import BaseModel, Field, field_validator

DialFilesToolName = Literal[
    "list",
    "read_lines",
    "search",
    "write",
    "edit",
    "delete",
    "copy",
    "move",
]


class DialFilesConfig(BaseModel):
    enabled_tools: Literal["all"] | list[DialFilesToolName] = Field(
        default="all",
        description=(
            "Which file tools to expose. Use 'all' for every tool, "
            "or a list to restrict (e.g. ['read_lines', 'search'])."
        ),
    )
    agent_home_dir: str = Field(
        default="",
        description=(
            "Optional sub-directory inside the agent's appdata folder used as the "
            "root for relative paths. Empty (default) means the appdata root. "
            "Must be a relative path; absolute 'files/...' URLs, leading '/', "
            "and '..' segments are rejected. Example: 'workspace/'."
        ),
    )

    @field_validator("agent_home_dir")
    @classmethod
    def _validate_agent_home_dir(cls, value: str) -> str:
        if value == "":
            return value
        if value.startswith("/"):
            raise ValueError("agent_home_dir must not start with '/'")
        if value.startswith("files/"):
            raise ValueError(
                "agent_home_dir must be a relative path under appdata, not an absolute 'files/' URL"
            )
        if not value.endswith("/"):
            raise ValueError("agent_home_dir must end with '/'")
        segments = value.split("/")
        if ".." in segments:
            raise ValueError("agent_home_dir must not contain '..' segments")
        if "" in segments[:-1]:
            raise ValueError("agent_home_dir must not contain empty segments")
        return value
