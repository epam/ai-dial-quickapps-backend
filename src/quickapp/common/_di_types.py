from typing import Annotated, Any

from aidial_sdk.chat_completion import ResponseFormat
from aidial_sdk.chat_completion.request import ToolChoice
from openai.lib.azure import AsyncAzureOpenAI
from pydantic import SecretStr

DIAL_API_KEY = Annotated[SecretStr, "DIAL_API_KEY"]
DIAL_BEARER = Annotated[SecretStr | None, "DIAL_BEARER"]
RESPONSE_FORMAT = Annotated[ResponseFormat | None, "RESPONSE_FORMAT"]
TOOL_CHOICE = Annotated[ToolChoice | str | None, "TOOL_CHOICE"]
EXTERNAL_TOOL_NAMES = Annotated[frozenset[str], "EXTERNAL_TOOL_NAMES"]
ForwardedHeaders = Annotated[dict[str, str] | None, "ForwardedHeaders"]
CLIENT_CHANNEL_ID = Annotated[str | None, "CLIENT_CHANNEL_ID"]
CLIENT_CHANNEL_HEADER = "X-DIAL-CLIENT-CHANNEL-ID"
ORCHESTRATOR_AZURE_CLIENT = Annotated[AsyncAzureOpenAI, "ORCHESTRATOR_AZURE_CLIENT"]
DEPLOYMENT_AZURE_CLIENT = Annotated[AsyncAzureOpenAI, "DEPLOYMENT_AZURE_CLIENT"]
# Value type is ArgumentStreamPresentation; Any avoids importing chat_completion_stream
# from common package init (circular). dict providers use @multiprovider.
ARGUMENT_STREAM_PRESENTATIONS = Annotated[dict[str, Any], "ARGUMENT_STREAM_PRESENTATIONS"]
SUPPRESSED_TOOL_STAGE_NAMES = Annotated[frozenset[str], "SUPPRESSED_TOOL_STAGE_NAMES"]
TOOL_STAGE_DISPLAY_NAMES = Annotated[dict[str, str], "TOOL_STAGE_DISPLAY_NAMES"]
