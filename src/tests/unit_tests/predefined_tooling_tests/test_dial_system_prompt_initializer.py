from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.exceptions import ConfigResolutionException
from quickapp.config.prompt import CustomSystemPromptConfig, DialSystemPromptConfig
from quickapp.predefined_tooling._dial_system_prompt_initializer import _DialSystemPromptInitializer
from quickapp.predefined_tooling._predefined_tooling_context import _PredefinedToolingContext
from tests.unit_tests.common.common import create_app_configuration, make_provider


def _make_initializer(
    system_prompt, dial_client: MagicMock, context: _PredefinedToolingContext
) -> _DialSystemPromptInitializer:
    config = create_app_configuration([])
    config.orchestrator.system_prompt = system_prompt
    return _DialSystemPromptInitializer(
        config_provider=make_provider(config),
        dial_client=dial_client,
        context=context,
    )


def _make_client(content: str | None = None, error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    client.prompts.get = AsyncMock(return_value=MagicMock(content=content), side_effect=error)
    return client


def test_runs_before_other_initializers():
    assert _DialSystemPromptInitializer.order < -100


@pytest.mark.asyncio
async def test_fills_content():
    prompt = DialSystemPromptConfig(path="prompts/b/p")
    client = _make_client(content="Be brief")

    await _make_initializer(prompt, client, _PredefinedToolingContext()).initialize()

    assert prompt.content == "Be brief"
    client.prompts.get.assert_awaited_once_with("prompts/b/p")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [_make_client(error=ResourceNotFoundError("missing")), _make_client(content="  ")],
    ids=["fetch_error", "empty_content"],
)
async def test_failure_is_recorded_and_raised(client: MagicMock):
    context = _PredefinedToolingContext()
    prompt = DialSystemPromptConfig(path="prompts/b/p")

    with pytest.raises(ConfigResolutionException) as excinfo:
        await _make_initializer(prompt, client, context).initialize()

    assert context.exceptions == [excinfo.value]
    assert excinfo.value.template_name == "prompts/b/p"


@pytest.mark.asyncio
async def test_other_prompt_types_make_no_fetch():
    client = _make_client(content="unused")
    prompt = CustomSystemPromptConfig(content="Own prompt", variables={})

    await _make_initializer(prompt, client, _PredefinedToolingContext()).initialize()

    client.prompts.get.assert_not_awaited()
    assert prompt.content == "Own prompt"
