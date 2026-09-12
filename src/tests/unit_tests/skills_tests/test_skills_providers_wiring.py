"""DI wiring for the three skill providers — each module contributes its own
adapter to ``list[SkillsProvider]`` via ``@multiprovider``."""

from unittest.mock import MagicMock

from aidial_client import AsyncDial
from fastapi_injector import Injected, request_scope
from injector import Binder, Module, ProviderOf
from starlette.testclient import TestClient

from quickapp.common.exceptions import InitializationException
from quickapp.dial_prompt_skills import _DialPromptSkillsContext
from quickapp.dial_prompt_skills.dial_prompt_skills_module import DialPromptSkillsModule
from quickapp.dial_skills.dial_skills_module import DialSkillsModule
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills.skills_module import SkillsModule
from quickapp.skills.skills_provider import ResolvedSkill, SkillsProvider
from tests.unit_tests.common.common import create_test_app


class _StubDialClientModule(Module):
    """Binds the DIAL client the skill providers fetch through."""

    def configure(self, binder: Binder) -> None:
        binder.bind(AsyncDial, to=lambda: MagicMock(spec=AsyncDial), scope=request_scope)


def _make_client(modules: list[Module]) -> TestClient:
    app = create_test_app([_StubDialClientModule(), *modules])

    @app.get("/source-types")
    async def source_types(
        sources: list[SkillsProvider] = Injected(list[SkillsProvider]),
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

    @app.get("/collision-reaches-aggregate")
    async def collision_reaches_aggregate(
        providers: list[SkillsProvider] = Injected(list[SkillsProvider]),
        registry: SkillsRegistry = Injected(SkillsRegistry),
        context: _DialPromptSkillsContext = Injected(_DialPromptSkillsContext),
        # Resolved lazily, exactly as _InitializationErrorHandler takes it.
        exceptions_provider: ProviderOf[list[InitializationException]] = Injected(
            ProviderOf[list[InitializationException]]
        ),
    ) -> list[str]:
        predefined_name = providers[0].resolved_skills[0].metadata.name
        context.extend_resolved_skills(
            [
                ResolvedSkill(
                    url="prompts/b/collides",
                    metadata=SkillMetadata(name=predefined_name, description="d"),
                    content="loser",
                )
            ]
        )
        # The merge runs during setup_messages...
        await registry.get_prompt_part()
        # ...and only afterwards does the handler resolve the aggregate.
        return [
            exc.reason
            for exc in exceptions_provider.get()
            if "already provided by" in getattr(exc, "reason", "")
        ]

    return TestClient(app)


class TestSkillSourcesWiring:

    def test_all_three_sources_are_injected(self):
        client = _make_client([SkillsModule(), DialPromptSkillsModule(), DialSkillsModule()])

        response = client.get("/source-types")

        assert response.status_code == 200
        assert response.json() == sorted(
            [
                "AgentSkillsProvider",
                "_DialPromptSkillsContext",
                "_DialSkillsContext",
            ]
        )

    def test_registry_resolves_with_only_always_on_sources(self):
        # Mirrors ENABLE_PREVIEW_FEATURES=false: DialSkillsModule omitted.
        client = _make_client([SkillsModule(), DialPromptSkillsModule()])

        types_response = client.get("/source-types")
        assert types_response.status_code == 200
        assert types_response.json() == sorted(["AgentSkillsProvider", "_DialPromptSkillsContext"])

        prompt_response = client.get("/prompt-part")
        assert prompt_response.status_code == 200

        read_response = client.get("/read-unknown-file")
        assert read_response.status_code == 200
        assert read_response.json() == {"error": "FileNotFoundError"}

    def test_registry_collisions_reach_the_aggregated_initialization_exceptions(self):
        """The registry owns collision exceptions rather than pushing them back
        into each provider, which only works because the aggregated
        ``list[InitializationException]`` is resolved lazily — after the merge.
        """
        client = _make_client([SkillsModule(), DialPromptSkillsModule()])

        response = client.get("/collision-reaches-aggregate")

        assert response.status_code == 200
        assert response.json() == [
            "Skill 'tool-call-file-parameter-formatting' is already provided by"
            " predefined skills; this definition is ignored."
        ]

    def test_source_registration_order_does_not_depend_on_module_list_order(self):
        # Real precedence data is covered by
        # test_precedence_is_independent_of_source_list_order (registry_dial_skills tests).
        forward = _make_client([SkillsModule(), DialPromptSkillsModule(), DialSkillsModule()])
        reversed_order = _make_client(
            [DialSkillsModule(), DialPromptSkillsModule(), SkillsModule()]
        )

        assert forward.get("/source-types").json() == reversed_order.get("/source-types").json()
