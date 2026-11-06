from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client import AsyncDial
from fastapi_injector import Injected, request_scope
from injector import Binder, Module
from starlette.testclient import TestClient

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.dial_settings import DialSettings
from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services.dial_downloader import DialDownloader
from quickapp.file_transfer import FileSource, FileTransferModule
from quickapp.file_transfer._file_loader_service import FileLoaderService
from quickapp.file_transfer._file_prefix_handlers import FilePrefixHandlers
from quickapp.shared.external_fetch.external_url_fetcher import ExternalUrlFetcher
from quickapp.skills.file_reference._skill_file_source import _SkillFileSource
from quickapp.skills.file_reference.skill_file_reference_module import SkillFileReferenceModule
from quickapp.skills.registry._skills_registry import SkillsRegistry
from quickapp.skills.registry.skills_module import SkillsModule
from quickapp.skills.skills_di import skills_module
from tests.unit_tests.common.common import create_test_app


class _StubDialClientModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(AsyncDial, to=lambda: MagicMock(spec=AsyncDial), scope=request_scope)


def _make_client(modules: list[Module]) -> TestClient:
    app = create_test_app([_StubDialClientModule(), *modules])

    @app.get("/file-sources")
    async def file_sources(
        sources: list[FileSource] = Injected(list[FileSource]),
    ) -> list[str]:
        return [type(s).__name__ for s in sources]

    @app.get("/transformers")
    async def transformers(
        items: list[ToolArgumentTransformer] = Injected(list[ToolArgumentTransformer]),
    ) -> list[str]:
        return [type(t).__name__ for t in items]

    return TestClient(app)


class TestWiring:

    def test_module_is_part_of_the_skills_module_array(self):
        assert any(isinstance(m, SkillFileReferenceModule) for m in skills_module)

    def test_contributes_file_source_and_transformer(self):
        client = _make_client([SkillsModule(), FileTransferModule(), SkillFileReferenceModule()])

        assert client.get("/file-sources").json() == ["_SkillFileSource"]

    def test_contributes_argument_transformer(self):
        client = _make_client([SkillsModule(), SkillFileReferenceModule()])

        assert client.get("/transformers").json() == ["_SkillFileReferenceTransformer"]

    def test_file_sources_are_empty_without_the_feature(self):
        client = _make_client([FileTransferModule()])

        assert client.get("/file-sources").json() == []


@pytest.mark.asyncio
async def test_text_prefix_inlines_the_skill_file_unchanged():
    registry = MagicMock(spec=SkillsRegistry)
    registry.read_skill_file = AsyncMock(return_value="print('hi')\n")
    settings = MagicMock(spec=DialSettings)
    settings.url = "https://dial.example.com"
    loader = FileLoaderService(
        dial_downloader=MagicMock(spec=DialDownloader),
        external_fetcher=MagicMock(spec=ExternalUrlFetcher),
        state_holder=StateHolder(),
        dial_settings=settings,
        file_sources=[_SkillFileSource(registry)],
    )

    text = await FilePrefixHandlers.handle_text("skill://s/scripts/a.py", loader)
    encoded = await FilePrefixHandlers.handle_base64("skill://s/scripts/a.py", loader)

    assert text == "print('hi')\n"
    assert encoded == "cHJpbnQoJ2hpJykK"
    registry.read_skill_file.assert_awaited_once_with("s", "scripts/a.py")
