"""DI wiring for the three skill sources.

``SkillsRegistry`` declares both external contexts as ``T | None = None``, so a
module that failed to bind one would not raise — the registry would silently
serve fewer skills. These tests resolve it through a real container to prove
each source is actually connected.
"""

from unittest.mock import MagicMock

from aidial_client import AsyncDial
from fastapi_injector import Injected, request_scope
from injector import Binder, Module
from starlette.testclient import TestClient

from quickapp.dial_prompt_skills._dial_prompt_skills_context import _DialPromptSkillsContext
from quickapp.dial_prompt_skills.dial_prompt_skills_module import DialPromptSkillsModule
from quickapp.dial_skills import DialSkillReader, _DialSkillsContext
from quickapp.dial_skills.dial_skills_module import DialSkillsModule
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills.skills_module import SkillsModule
from tests.unit_tests.common.common import create_test_app


class _StubDialClientModule(Module):
    """Binds the DIAL client the skill sources fetch through."""

    def configure(self, binder: Binder) -> None:
        binder.bind(AsyncDial, to=lambda: MagicMock(spec=AsyncDial), scope=request_scope)


def _make_client() -> TestClient:
    app = create_test_app(
        [
            _StubDialClientModule(),
            SkillsModule(),
            DialPromptSkillsModule(),
            DialSkillsModule(),
        ]
    )

    @app.get("/wiring")
    async def wiring(registry: SkillsRegistry = Injected(SkillsRegistry)) -> dict[str, bool]:
        return {
            "prompt_context": isinstance(
                registry._context, _DialPromptSkillsContext  # noqa: SLF001
            ),
            "skills_context": isinstance(
                registry._dial_skills_context, _DialSkillsContext  # noqa: SLF001
            ),
            "skills_reader": isinstance(
                registry._dial_skill_reader, DialSkillReader  # noqa: SLF001
            ),
        }

    return TestClient(app)


class TestSkillSourcesWiring:

    def test_both_external_sources_are_injected(self):
        response = _make_client().get("/wiring")

        assert response.status_code == 200
        # None of the three may be left at its None default.
        assert response.json() == {
            "prompt_context": True,
            "skills_context": True,
            "skills_reader": True,
        }
