import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import openai
from mcp import McpError

from quickapp.common.exceptions import ToolTimeoutError

MCP_TIMEOUT_CODE: int = int(httpx.codes.REQUEST_TIMEOUT)

# `connect` is held at 5s so dead deployments fast-fail regardless of the
# configured tool timeout; read/write/pool all track the resolved value.
_ASYNC_DIAL_CONNECT_TIMEOUT_SECONDS: float = 5.0


def build_async_dial_timeout(timeout_seconds: float) -> openai.Timeout:
    """Return the `openai.Timeout` shape applied to every `AsyncDial` client."""
    return openai.Timeout(
        connect=_ASYNC_DIAL_CONNECT_TIMEOUT_SECONDS,
        read=timeout_seconds,
        write=timeout_seconds,
        pool=timeout_seconds,
    )


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError, openai.APITimeoutError)):
        return True
    if isinstance(exc, McpError):
        return getattr(exc.error, "code", None) == MCP_TIMEOUT_CODE
    return False


@asynccontextmanager
async def translate_timeout(tool_name: str, timeout_seconds: float) -> AsyncIterator[None]:
    """Enforce wall-clock timeout and translate recognised timeouts to `ToolTimeoutError`.

    The `asyncio.timeout` wrapper is load-bearing: streaming tool calls
    (DIAL deployment SSE) have only an *idle-read* phase timeout at the
    client layer, so a chatty server would otherwise run unbounded. The
    fired `TimeoutError` is absorbed by the `asyncio.TimeoutError` branch
    below and surfaces as `ToolTimeoutError`.
    """
    try:
        async with asyncio.timeout(timeout_seconds):
            yield
    except BaseExceptionGroup as eg:
        timeout_leaves, _ = eg.split(_is_timeout)
        if timeout_leaves is not None:
            raise ToolTimeoutError(tool_name, timeout_seconds) from eg
        raise
    except McpError as e:
        if getattr(e.error, "code", None) == MCP_TIMEOUT_CODE:
            raise ToolTimeoutError(tool_name, timeout_seconds) from e
        raise
    except (httpx.TimeoutException, asyncio.TimeoutError, openai.APITimeoutError) as e:
        raise ToolTimeoutError(tool_name, timeout_seconds) from e
