from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import MessageContentImagePart, MessageContentTextPart
from fastapi_injector import Injected, request_scope
from injector import Binder, Module, multiprovider
from starlette.testclient import TestClient

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.config.agent_settings import AgentSettings
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent._messages_transformers import _AddSystemPromptTransformer
from quickapp.core.agent._prompt_providers import ConfigBasedPromptProvider
from tests.unit_tests.common.common import create_test_app


def _provider(spec: type, part: str) -> MagicMock:
    provider = MagicMock(spec=spec)
    provider.get_prompt_part = AsyncMock(return_value=part)
    return provider


def _make_transformer(
    config_part: str = "CONFIG", extra_part: str = "SKILLS", allow_override: bool = False
) -> _AddSystemPromptTransformer:
    config = _provider(ConfigBasedPromptProvider, config_part)
    parts: list[PromptPartProvider] = [config]
    if extra_part:
        parts.append(_provider(PromptPartProvider, extra_part))  # type: ignore[type-abstract]
    settings = AgentSettings(ALLOW_OVERRIDE_SYSTEM_MESSAGE=allow_override)  # type: ignore[call-arg]
    return _AddSystemPromptTransformer(parts, settings)


def _user() -> Message:
    return Message(role=Role.USER, content="hi")


def _system(content: str | list | None = "INBOUND") -> Message:
    return Message(role=Role.SYSTEM, content=content)


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_override", [False, True])
async def test_prepends_system_when_none_inbound(allow_override):
    result = await _make_transformer(allow_override=allow_override).transform([_user()])

    assert [m.role for m in result] == [Role.SYSTEM, Role.USER]
    assert result[0].content == "CONFIG\n\nSKILLS"


@pytest.mark.asyncio
async def test_inbound_system_discarded_by_default():
    result = await _make_transformer().transform([_system(), _user()])

    assert [m.role for m in result] == [Role.SYSTEM, Role.USER]
    assert result[0].content == "CONFIG\n\nSKILLS"
    assert "INBOUND" not in result[0].content


@pytest.mark.asyncio
async def test_inbound_system_replaces_config_prompt_when_allowed():
    result = await _make_transformer(allow_override=True).transform([_system(), _user()])

    assert [m.role for m in result] == [Role.SYSTEM, Role.USER]
    assert result[0].content == "INBOUND\n\nSKILLS"
    assert "CONFIG" not in result[0].content


@pytest.mark.asyncio
async def test_text_parts_inbound_system_are_joined_when_allowed():
    inbound = _system(
        [
            MessageContentTextPart(type="text", text="A"),
            MessageContentTextPart(type="text", text="B"),
        ]
    )

    result = await _make_transformer(allow_override=True).transform([inbound, _user()])

    assert result[0].content == "A\nB\n\nSKILLS"


@pytest.mark.asyncio
async def test_text_parts_inbound_system_discarded_by_default():
    inbound = _system([MessageContentTextPart(type="text", text="A")])

    result = await _make_transformer().transform([inbound, _user()])

    assert result[0].content == "CONFIG\n\nSKILLS"


@pytest.mark.asyncio
async def test_non_text_parts_inbound_system_falls_back_to_config_and_warns(caplog):
    inbound = _system(
        [MessageContentImagePart(type="image_url", image_url={"url": "http://x/y.png"})]
    )

    with caplog.at_level("WARNING"):
        result = await _make_transformer(allow_override=True).transform([inbound, _user()])

    assert result[0].content == "CONFIG\n\nSKILLS"
    assert "no text content" in caplog.text


@pytest.mark.asyncio
async def test_empty_inbound_system_falls_back_to_config_when_allowed():
    result = await _make_transformer(allow_override=True).transform([_system(""), _user()])

    assert result[0].content == "CONFIG\n\nSKILLS"


@pytest.mark.asyncio
async def test_inbound_system_dropped_when_generated_prompt_empty():
    result = await _make_transformer(config_part="", extra_part="").transform([_system(), _user()])

    assert [m.role for m in result] == [Role.USER]


class _OverrideWiringModule(Module):
    """Real request-scoped wiring: the config provider reaches the transformer through the list."""

    def configure(self, binder: Binder) -> None:
        config = MagicMock()
        config.orchestrator.system_prompt.content = "CONFIG"
        binder.bind(ApplicationConfig, to=lambda: config, scope=request_scope)
        binder.bind(
            AgentSettings,
            to=AgentSettings(ALLOW_OVERRIDE_SYSTEM_MESSAGE=True),  # type: ignore[call-arg]
        )
        binder.bind(ConfigBasedPromptProvider, to=ConfigBasedPromptProvider, scope=request_scope)
        binder.bind(
            _AddSystemPromptTransformer, to=_AddSystemPromptTransformer, scope=request_scope
        )

    @multiprovider
    def _provide_prompt_providers(
        self, config: ConfigBasedPromptProvider
    ) -> list[PromptPartProvider]:
        return [config]


def test_override_replaces_config_prompt_through_the_real_container():
    app = create_test_app(_OverrideWiringModule())

    @app.get("/system")
    async def system(
        transformer: _AddSystemPromptTransformer = Injected(_AddSystemPromptTransformer),
    ) -> str:
        result = await transformer.transform([_system(), _user()])
        return str(result[0].content)

    response = TestClient(app).get("/system")

    assert response.status_code == 200
    assert response.json() == "INBOUND"
