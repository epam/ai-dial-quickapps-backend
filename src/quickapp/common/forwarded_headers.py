"""Forwarded request headers (e.g. X-*) to be passed to MCP and ChatCompletion requests."""


def extract_x_headers_from_request(request) -> dict[str, str]:
    """
    Extract all headers whose names start with "X-" (case-insensitive) from the given
    SDK Request. Uses original_request.headers when available, otherwise request.headers.
    """
    headers: dict[str, str] = {}
    raw = getattr(request, "original_request", None)
    if raw is not None and hasattr(raw, "headers"):
        # Starlette/FastAPI request headers (case-insensitive multidict)
        for name, value in raw.headers.items():
            if name.lower().startswith("x-"):
                headers[name] = value
        return headers
    raw_headers = getattr(request, "headers", None)
    if isinstance(raw_headers, dict):
        for name, value in raw_headers.items():
            if name.lower().startswith("x-"):
                headers[name] = str(value)
    return headers


class ForwardedHeaders:
    """Container for headers to forward to downstream MCP and ChatCompletion requests."""

    __slots__ = ("_headers",)

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self._headers = dict(headers) if headers else {}

    @property
    def headers(self) -> dict[str, str]:
        return self._headers
