"""Forwarded request headers (e.g. X-*) to be passed to MCP and ChatCompletion requests."""

from aidial_sdk.chat_completion import Request

from quickapp.common import ForwardedHeaders


def extract_x_headers_from_request(request: Request) -> ForwardedHeaders:
    """
    Extract all headers whose names start with "X-" (case-insensitive) from the given
    SDK Request. Uses original_request.headers when available, otherwise request.headers.
    """
    headers: ForwardedHeaders = None
    raw_headers = request.headers
    if isinstance(raw_headers, dict):
        for name, value in raw_headers.items():
            if name.lower().startswith("x-"):
                if headers is None:
                    headers = {}
                headers[name] = str(value)
    return headers
