import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import openai
from mcp import McpError

from quickapp.common.exceptions import ToolTimeoutError

MCP_TIMEOUT_CODE: int = int(httpx.codes.REQUEST_TIMEOUT)


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError, openai.APITimeoutError)):
        return True
    if isinstance(exc, McpError):
        return getattr(exc.error, "code", None) == MCP_TIMEOUT_CODE
    return False


@asynccontextmanager
async def translate_timeout(tool_name: str, timeout_seconds: float) -> AsyncIterator[None]:
    """Catch recognised timeout exceptions and re-raise as `ToolTimeoutError`."""
    try:
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
