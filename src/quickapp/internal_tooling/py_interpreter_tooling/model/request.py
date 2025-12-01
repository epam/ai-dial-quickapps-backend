from pydantic import BaseModel, Field


class InputFileTransfer(BaseModel):
    sourceUrl: str | None = Field(default=None)
    targetPath: str | None = Field(default=None)


class OutputFileTransfer(BaseModel):
    sourcePath: str | None = Field(default=None)
    targetUrl: str | None = Field(default=None)


class CodeExecutionRequest(BaseModel):
    sessionId: str | None = Field(default=None)
    code: str
    inputFiles: list[InputFileTransfer] = Field(default_factory=list)
    outputFiles: list[OutputFileTransfer] = Field(default_factory=list)


class InputFileTransferDto(InputFileTransfer):
    sessionId: str
