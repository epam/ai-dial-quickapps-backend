from typing import Any

# DIAL extensions of the chat completion request, sent through the openai client's `extra_body`.
EXTRA_BODY = "extra_body"
CUSTOM_FIELDS = "custom_fields"
CONFIGURATION = "configuration"


def to_custom_fields_payload(custom_fields: dict[str, Any]) -> dict[str, Any]:
    """Drop an empty `configuration`; keep other keys as-is, since e.g. `cache_breakpoint: {}` is meaningful."""
    return {
        key: value
        for key, value in custom_fields.items()
        if not (key == CONFIGURATION and not value)
    }
