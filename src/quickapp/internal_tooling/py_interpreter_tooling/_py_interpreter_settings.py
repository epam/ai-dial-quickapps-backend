from typing import Annotated

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_PY_INTERPRETER_API_KEY = Annotated[SecretStr, "PY_INTERPRETER_API_KEY"]


class _PyInterpreterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='py_interpreter_')

    local_run: bool = Field(
        default=False,
        description="Run the PyInterpreter locally or use the DIAL Core API",
    )
    url: str = Field(
        default="",
        description="The URL of the PyInterpreter service or DIAL Core API",
    )
    api_key: SecretStr = Field(
        default=SecretStr(""),
        description="API key for local run of the PyInterpreter",
    )
    default_session_id: str | None = Field(
        default=None,
        description="Default session ID for the PyInterpreter",
    )
    additional_handling_model: str = Field(
        default="gpt-4o-mini-2024-07-18",
        description="Model used for additional handling in the PyInterpreter",
    )
    client_timeout: float = Field(
        default=60.0,
        description="Timeout for the PyInterpreter client requests in seconds",
    )
    client_max_retries: int = Field(
        default=3,
        description="Maximum number of retries for the PyInterpreter client requests",
    )
