from typing import Annotated

from aidial_sdk.chat_completion import Choice, Message, Request, ResponseFormat
from aidial_sdk.chat_completion.request import Tool
from aidial_sdk.deployment.configuration import ConfigurationRequest
from pydantic import BaseModel, ConfigDict, Field, SecretStr, SkipValidation

from quickapp.common._di_types import TOOL_CHOICE, ForwardedHeaders
from quickapp.common.forwarded_headers import extract_x_headers_from_request
from quickapp.config.application import ApplicationConfig


class CompletionInputs(BaseModel):
    """Everything one completion run needs, independent of where it came from.

    The HTTP handler builds this from the SDK request; a subagent spawn builds it
    from values it already holds. Either way ``CompletionRunner`` sees the same shape.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    api_key: SecretStr
    bearer: SecretStr | None = None
    application_config: ApplicationConfig = Field(
        description="Raw manifest; `_RequestContextSetup` runs `ConfigResolver` over it."
    )
    messages: list[Message] = Field(default_factory=list)
    # The SDK Choice is not a Pydantic model; it is passed through, never validated.
    choice: Annotated[Choice | None, SkipValidation] = None
    forwarded_headers: ForwardedHeaders = None
    accept_language: str | None = None
    response_format: ResponseFormat | None = None
    tool_choice: TOOL_CHOICE = None
    extra_tools: list[Tool] = Field(default_factory=list)

    @classmethod
    async def from_request(
        cls,
        request: Request | ConfigurationRequest,
        choice: Choice | None = None,
        language_header: str | None = None,
    ) -> "CompletionInputs":
        """The only place the SDK request is read."""
        application_config = ApplicationConfig.model_validate(
            await request.request_dial_application_properties()
        )
        if not isinstance(request, Request):
            return cls(
                api_key=SecretStr(request.api_key),
                bearer=_bearer(request),
                application_config=application_config,
                choice=choice,
            )
        return cls(
            api_key=SecretStr(request.api_key),
            bearer=_bearer(request),
            application_config=application_config,
            messages=request.messages,
            choice=choice,
            forwarded_headers=extract_x_headers_from_request(request),
            accept_language=request.headers.get(language_header) if language_header else None,
            response_format=request.response_format,
            tool_choice=request.tool_choice,
            extra_tools=[t for t in request.tools or [] if isinstance(t, Tool)],
        )


def _bearer(request: Request | ConfigurationRequest) -> SecretStr | None:
    return SecretStr(request.bearer_token) if request.bearer_token else None
