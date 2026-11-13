from unittest.mock import MagicMock

import pytest

from quickapp.common.exceptions import OrchestratorSystemPromptException
from quickapp.config.prompt import CustomSystemPromptConfig, DialSystemPromptConfig
from quickapp.core.agent._dial_system_prompt_initializer import _DialSystemPromptInitializer
from quickapp.dial_app_tooling._dial_app_resolver import _DialAppResolver
from quickapp.dial_core_services.exceptions import DialPromptLoadError
from tests.unit_tests.common.common import create_app_configuration, make_prompt_loader


def _make_initializer(system_prompt, loader: MagicMock) -> _DialSystemPromptInitializer:
    config = create_app_configuration([])
    config.orchestrator.system_prompt = system_prompt
    return _DialSystemPromptInitializer(app_config=config, prompt_loader=loader)


def test_runs_before_other_initializers():
    assert _DialSystemPromptInitializer.order < _DialAppResolver.order


@pytest.mark.asyncio
async def test_fills_content():
    prompt = DialSystemPromptConfig(path="prompts/b/p")
    loader = make_prompt_loader(content="Be brief")

    await _make_initializer(prompt, loader).initialize()

    assert prompt.content == "Be brief"
    loader.load.assert_awaited_once_with("prompts/b/p")


@pytest.mark.asyncio
async def test_failure_is_recorded_and_raised():
    prompt = DialSystemPromptConfig(path="prompts/b/p")
    initializer = _make_initializer(
        prompt, make_prompt_loader(error=DialPromptLoadError("no content"))
    )

    with pytest.raises(OrchestratorSystemPromptException) as excinfo:
        await initializer.initialize()

    assert initializer.initialization_exceptions == [excinfo.value]
    assert str(excinfo.value) == "System prompt 'prompts/b/p' could not be loaded: no content"


@pytest.mark.asyncio
async def test_other_prompt_types_make_no_fetch():
    loader = make_prompt_loader(content="unused")
    prompt = CustomSystemPromptConfig(content="Own prompt", variables={})

    await _make_initializer(prompt, loader).initialize()

    loader.load.assert_not_awaited()
    assert prompt.content == "Own prompt"
