import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client import InvalidDialURLError, NotDialURLError, ResourceNotFoundError

from quickapp.dial_core_services.dial_prompt_loader import DialPromptLoader
from quickapp.dial_core_services.exceptions import DialPromptLoadError


def _make_client(content: str | None = None, error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    client.prompts.get = AsyncMock(return_value=MagicMock(content=content), side_effect=error)
    return client


@pytest.mark.asyncio
async def test_returns_prompt_content():
    client = _make_client(content="Be brief")

    assert await DialPromptLoader(client).load("prompts/b/p") == "Be brief"
    client.prompts.get.assert_awaited_once_with("prompts/b/p")


@pytest.mark.asyncio
async def test_dial_error_message_hides_the_response_body(caplog):
    client = _make_client(error=ResourceNotFoundError("raw-response-body"))

    with caplog.at_level(logging.DEBUG), pytest.raises(DialPromptLoadError) as excinfo:
        await DialPromptLoader(client).load("prompts/b/p")

    assert str(excinfo.value) == "DIAL prompt could not be loaded (status 404)"
    assert "raw-response-body" not in caplog.text
    assert "prompts/b/p" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [InvalidDialURLError("Invalid resource type: bucket"), NotDialURLError("Not a DIAL URL")],
    ids=["invalid_dial_url", "not_dial_url"],
)
async def test_invalid_path_names_the_expected_format(error: Exception):
    client = _make_client(error=error)

    with pytest.raises(DialPromptLoadError, match="expected prompts/<bucket>/<path>"):
        await DialPromptLoader(client).load("bucket/p")


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [None, "", "   \n"])
async def test_empty_content_raises(content: str | None):
    client = _make_client(content=content)

    with pytest.raises(DialPromptLoadError, match="no content"):
        await DialPromptLoader(client).load("prompts/b/p")


@pytest.mark.asyncio
async def test_prompt_body_is_not_logged(caplog):
    client = _make_client(content="secret-prompt-body")

    with caplog.at_level(logging.DEBUG):
        await DialPromptLoader(client).load("prompts/b/p")

    assert "secret-prompt-body" not in caplog.text
