"""DI wiring for the three skill sources — each module contributes its own
adapter to ``list[SkillSource]`` via ``@multiprovider``."""

from unittest.mock import MagicMock

from aidial_client import AsyncDial
from fastapi_injector import Injected, request_scope
from injector import Binder, Module
from starlette.testclient import TestClient

from quickapp.dial_prompt_skills.dial_prompt_skills_module import DialPromptSkillsModule
from quickapp.dial_skills.dial_skills_module import DialSkillsModule
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills.skill_source import SkillSource
from quickapp.skills.skills_module import SkillsModule
from tests.unit_tests.common.common import create_test_app


class _StubDialClientModule(Module):
    """Binds the DIAL client the skill sources fetch through."""

    def configure(self, binder: Binder) -> None:
        binder.bind(AsyncDial, to=lambda: MagicMock(spec=AsyncDial), scope=request_scope)


def _make_client(modules: list[Module]) -> TestClient:
    app = create_test_app([_StubDialClientModule(), *modules])

    @app.get("/source-types")
    async def source_types(
        sources: list[SkillSource] = Injected(list[SkillSource]),
    ) -> list[str]:
        return sorted(type(s).__name__ for s in sources)

    @app.get("/prompt-part")
    async def prompt_part(registry: SkillsRegistry = Injected(SkillsRegistry)) -> str:
        return await registry.get_prompt_part()

    @app.get("/read-unknown-file")
    async def read_unknown_file(
        registry: SkillsRegistry = Injected(SkillsRegistry),
    ) -> dict[str, str]:
        try:
            await registry.read_skill_file("nope", "a.md")
        except FileNotFoundError as exc:
            return {"error": type(exc).__name__}
        return {"error": "none"}

    return TestClient(app)


class TestSkillSourcesWiring:

    def test_all_three_sources_are_injected(self):
        client = _make_client([SkillsModule(), DialPromptSkillsModule(), DialSkillsModule()])

        response = client.get("/source-types")

        assert response.status_code == 200
        assert response.json() == sorted(
            [
                "_PredefinedSkillsSource",
                "_DialPromptSkillsSource",
                "_DialSkillsSource",
            ]
        )

    def test_registry_resolves_with_only_always_on_sources(self):
        # Mirrors ENABLE_PREVIEW_FEATURES=false: DialSkillsModule omitted.
        client = _make_client([SkillsModule(), DialPromptSkillsModule()])

        types_response = client.get("/source-types")
        assert types_response.status_code == 200
        assert types_response.json() == sorted(
            ["_PredefinedSkillsSource", "_DialPromptSkillsSource"]
        )

        prompt_response = client.get("/prompt-part")
        assert prompt_response.status_code == 200

        read_response = client.get("/read-unknown-file")
        assert read_response.status_code == 200
        assert read_response.json() == {"error": "FileNotFoundError"}

    def test_source_registration_order_does_not_depend_on_module_list_order(self):
        # Real precedence data is covered by
        # test_precedence_is_independent_of_source_list_order (registry_dial_skills tests).
        forward = _make_client([SkillsModule(), DialPromptSkillsModule(), DialSkillsModule()])
        reversed_order = _make_client(
            [DialSkillsModule(), DialPromptSkillsModule(), SkillsModule()]
        )

        assert forward.get("/source-types").json() == reversed_order.get("/source-types").json()
