from typing import Annotated

from aidial_sdk.chat_completion import ResponseFormat
from pydantic import SecretStr

DIAL_API_KEY = Annotated[SecretStr, "DIAL_API_KEY"]
DIAL_BEARER = Annotated[SecretStr | None, "DIAL_BEARER"]
RESPONSE_FORMAT = Annotated[ResponseFormat | None, "RESPONSE_FORMAT"]
ForwardedHeaders = Annotated[dict[str, str] | None, "ForwardedHeaders"]
