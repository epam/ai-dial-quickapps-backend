import asyncio

import httpx
import openai
import pytest
from mcp import McpError
from mcp.types import ErrorData

from quickapp.common.exceptions import ToolTimeoutError
from quickapp.common.tool_timeout_utils import translate_timeout


@pytest.mark.asyncio
async def test_passes_through_when_no_exception():
    async with translate_timeout("my_tool", 30):
        pass  # no exception


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raised",
    [
        httpx.ReadTimeout("read timeout"),
        httpx.ConnectTimeout("connect timeout"),
        httpx.WriteTimeout("write timeout"),
        httpx.PoolTimeout("pool timeout"),
        asyncio.TimeoutError(),
        openai.APITimeoutError(request=httpx.Request("GET", "http://test")),
    ],
)
async def test_translates_library_timeouts(raised):
    with pytest.raises(ToolTimeoutError) as excinfo:
        async with translate_timeout("my_tool", 30):
            raise raised
    assert excinfo.value.tool_name == "my_tool"
    assert excinfo.value.timeout_seconds == 30
    assert "timed out" in str(excinfo.value)
    assert excinfo.value.__cause__ is raised


@pytest.mark.asyncio
async def test_translates_mcp_timeout_code():
    err = McpError(ErrorData(code=int(httpx.codes.REQUEST_TIMEOUT), message="timeout"))
    with pytest.raises(ToolTimeoutError):
        async with translate_timeout("my_tool", 5):
            raise err


@pytest.mark.asyncio
async def test_mcp_non_timeout_code_passes_through():
    err = McpError(ErrorData(code=-32600, message="invalid request"))
    with pytest.raises(McpError):
        async with translate_timeout("my_tool", 5):
            raise err


@pytest.mark.asyncio
async def test_non_timeout_exceptions_pass_through():
    with pytest.raises(ValueError, match="nope"):
        async with translate_timeout("my_tool", 5):
            raise ValueError("nope")


@pytest.mark.asyncio
async def test_exception_group_with_timeout_leaf_classifies_as_timeout():
    eg = BaseExceptionGroup("group", [ValueError("x"), asyncio.TimeoutError()])
    with pytest.raises(ToolTimeoutError) as excinfo:
        async with translate_timeout("my_tool", 5):
            raise eg
    assert excinfo.value.__cause__ is eg


@pytest.mark.asyncio
async def test_exception_group_without_timeout_leaf_passes_through():
    eg = BaseExceptionGroup("group", [ValueError("x"), RuntimeError("y")])
    with pytest.raises(BaseExceptionGroup):
        async with translate_timeout("my_tool", 5):
            raise eg


@pytest.mark.asyncio
async def test_exception_group_with_nested_timeout_leaf():
    inner = BaseExceptionGroup("inner", [httpx.ReadTimeout("t")])
    eg = BaseExceptionGroup("outer", [ValueError("x"), inner])
    with pytest.raises(ToolTimeoutError):
        async with translate_timeout("my_tool", 5):
            raise eg


@pytest.mark.asyncio
async def test_error_carries_timeout_value():
    with pytest.raises(ToolTimeoutError) as excinfo:
        async with translate_timeout("my_tool", 42):
            raise asyncio.TimeoutError()
    assert excinfo.value.timeout_seconds == 42
    assert "timed out" in str(excinfo.value)
    assert "42" in str(excinfo.value)
