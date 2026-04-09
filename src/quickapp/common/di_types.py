from typing import Annotated

from aidial_sdk.chat_completion import ResponseFormat
from pydantic import SecretStr

DIAL_API_KEY = Annotated[SecretStr, "DIAL_API_KEY"]
DIAL_BEARER = Annotated[SecretStr | None, "DIAL_BEARER"]
RESPONSE_FORMAT = Annotated[ResponseFormat | None, "RESPONSE_FORMAT"]
ForwardedHeaders = Annotated[dict[str, str] | None, "ForwardedHeaders"]
CLIENT_CHANNEL_ID = Annotated[str | None, "CLIENT_CHANNEL_ID"]
CLIENT_CHANNEL_HEADER = "X-DIAL-CLIENT-CHANNEL-ID"

# DI type for skill injection entries: (skill_name, tool_call_id).
# Each module that needs to inject a builtin skill at conversation start
# should provide entries via multiprovider.
BUILTIN_SKILLS_TO_INJECT = Annotated[list[tuple[str, str]], "BUILTIN_SKILLS_TO_INJECT"]
