from typing import Annotated, Optional

from aidial_sdk.chat_completion import ResponseFormat
from pydantic import SecretStr

DIAL_API_KEY = Annotated[SecretStr, "DIAL_API_KEY"]
DIAL_BEARER = Annotated[Optional[SecretStr], "DIAL_BEARER"]
RESPONSE_FORMAT = Annotated[Optional[ResponseFormat], "RESPONSE_FORMAT"]
