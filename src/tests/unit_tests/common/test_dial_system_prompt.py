import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import InvalidDialURLError, ResourceNotFoundError

from quickapp.common.dial_system_prompt import DialSystemPromptError, fetch_dial_system_prompt


def _make_client(content: str | None = None, error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    client.prompts.get = AsyncMock(return_value=MagicMock(content=content), side_effect=error)
    return client


@pytest.mark.asyncio
async def test_returns_prompt_content():
    client = _make_client(content="Be brief")

    assert await fetch_dial_system_prompt(client, "prompts/b/p") == "Be brief"
    client.prompts.get.assert_awaited_once_with("prompts/b/p")


@pytest.mark.asyncio
async def test_dial_error_message_hides_the_response_body(caplog):
    client = _make_client(error=ResourceNotFoundError("raw-response-body"))

    with caplog.at_level(logging.DEBUG), pytest.raises(DialSystemPromptError) as excinfo:
        await fetch_dial_system_prompt(client, "prompts/b/p")

    assert str(excinfo.value) == "DIAL prompt could not be loaded (status 404)"
    assert "raw-response-body" not in caplog.text
    assert "prompts/b/p" in caplog.text


@pytest.mark.asyncio
async def test_invalid_path_names_the_expected_format():
    client = _make_client(error=InvalidDialURLError("Invalid resource type: bucket"))

    with pytest.raises(DialSystemPromptError, match="expected prompts/<bucket>/<path>"):
        await fetch_dial_system_prompt(client, "bucket/p")


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [None, "", "   \n"])
async def test_empty_content_raises(content: str | None):
    client = _make_client(content=content)

    with pytest.raises(DialSystemPromptError, match="no content"):
        await fetch_dial_system_prompt(client, "prompts/b/p")


@pytest.mark.asyncio
async def test_prompt_body_is_not_logged(caplog):
    client = _make_client(content="secret-prompt-body")

    with caplog.at_level(logging.DEBUG):
        await fetch_dial_system_prompt(client, "prompts/b/p")

    assert "secret-prompt-body" not in caplog.text
