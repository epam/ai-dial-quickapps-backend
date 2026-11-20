from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> tuple[str, str, int | None] | None:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return None
    return scheme, host, port if port is not None else _DEFAULT_PORTS.get(scheme)


def is_dial_origin(url: str, dial_url: str) -> bool:
    """True when ``url`` has the same scheme, host and effective port as ``dial_url``."""
    origin = _origin(url)
    return origin is not None and origin == _origin(dial_url)
