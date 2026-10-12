from typing import Any

# DIAL extensions of the chat completion request, sent through the openai client's `extra_body`.
EXTRA_BODY = "extra_body"
CUSTOM_FIELDS = "custom_fields"
CONFIGURATION = "configuration"


def to_custom_fields_payload(custom_fields: dict[str, Any]) -> dict[str, Any]:
    configuration = custom_fields.get(CONFIGURATION)
    return {CONFIGURATION: configuration} if configuration else {}
