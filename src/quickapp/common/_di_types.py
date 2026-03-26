from typing import Annotated

from aidial_sdk.chat_completion import ResponseFormat
from openai.lib.azure import AsyncAzureOpenAI
from pydantic import SecretStr

DIAL_API_KEY = Annotated[SecretStr, "DIAL_API_KEY"]
DIAL_BEARER = Annotated[SecretStr | None, "DIAL_BEARER"]
RESPONSE_FORMAT = Annotated[ResponseFormat | None, "RESPONSE_FORMAT"]
ForwardedHeaders = Annotated[dict[str, str] | None, "ForwardedHeaders"]
CLIENT_CHANNEL_ID = Annotated[str | None, "CLIENT_CHANNEL_ID"]
CLIENT_CHANNEL_HEADER = "X-DIAL-CLIENT-CHANNEL-ID"
ORCHESTRATOR_AZURE_CLIENT = Annotated[AsyncAzureOpenAI, "ORCHESTRATOR_AZURE_CLIENT"]
DEPLOYMENT_AZURE_CLIENT = Annotated[AsyncAzureOpenAI, "DEPLOYMENT_AZURE_CLIENT"]

