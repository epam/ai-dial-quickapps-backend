from pydantic import BaseModel, Field


class PyInterpreterSession(BaseModel):
    sessionId: str | None = Field(default=None)
