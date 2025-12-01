from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExecutionStatus(Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class CodeExecutionResponse(BaseModel):
    status: ExecutionStatus
    result: dict[str, str] | str = Field(default="")
    stdout: str | None = Field(default=None)
    stderr: str | None = Field(default=None)
    display: list[dict[str, Any]] = Field(default_factory=list)


class File(BaseModel):
    path: str
    size: int


class LoadedFiles(BaseModel):
    files: list[File]
