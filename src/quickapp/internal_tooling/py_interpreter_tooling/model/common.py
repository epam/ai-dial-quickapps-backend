from pydantic import BaseModel, Field


class PyInterpreterSession(BaseModel):
    sessionId: str | None = Field(default=None)


class PyInterpreterState(BaseModel):
    session_id: str | None = Field(default=None)
