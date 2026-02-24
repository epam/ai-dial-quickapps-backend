"""Forwarded request headers (e.g. X-*) to be passed to MCP and ChatCompletion requests."""

from aidial_sdk.chat_completion import Request


def extract_x_headers_from_request(request: Request) -> dict[str, str]:
    """
    Extract all headers whose names start with "X-" (case-insensitive) from the given
    SDK Request. Uses original_request.headers when available, otherwise request.headers.
    """
    headers: dict[str, str] = {}
    raw_headers = request.headers
    if isinstance(raw_headers, dict):
        for name, value in raw_headers.items():
            if name.lower().startswith("x-"):
                headers[name] = str(value)
    return headers


class ForwardedHeaders:
    __slots__ = ("_headers",)

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self._headers = dict(headers) if headers else {}

    @property
    def headers(self) -> dict[str, str]:
        return self._headers
