from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.project_context import ProjectContext
from quickapp.config.dial_files import DialFilesConfig
from quickapp.dial_core_services.dial_file_service import DialFileService, FolderEntry
from quickapp.shared.project._project_prompt_provider import (
    MAX_CONTEXT_ENTRIES,
    MAX_INSTRUCTIONS_CHARS,
    _ProjectPromptProvider,
    strip_frontmatter,
)

PROJECT = ProjectContext(url="projects/b/My Project")
CONTEXT = "projects/b/My%20Project/files/context/"


def _service(
    instructions: str | None = "Answer in French.",
    context: list[FolderEntry] | None = None,
) -> MagicMock:
    service = MagicMock(spec=DialFileService)
    if instructions is None:
        service.download_file = AsyncMock(side_effect=ResourceNotFoundError(message="missing"))
    else:
        service.download_file = AsyncMock(return_value=(instructions.encode(), None))
    service.list_folder = AsyncMock(return_value=context or [])
    return service


def _provider(
    service: MagicMock,
    *,
    project: ProjectContext | None = PROJECT,
    file_tools: bool = True,
) -> _ProjectPromptProvider:
    features = SimpleNamespace(dial_files=DialFilesConfig() if file_tools else None)
    return _ProjectPromptProvider(
        project=project,
        app_config=SimpleNamespace(features=features),  # type: ignore[arg-type]
        dial_file_service=service,
    )


def _file(name: str) -> FolderEntry:
    return FolderEntry(url=f"{CONTEXT}{name}", is_folder=False, size=None)


class TestProjectPromptProvider:
    @pytest.mark.asyncio
    async def test_no_project_adds_nothing(self):
        service = _service()

        assert await _provider(service, project=None).get_prompt_part() == ""
        service.download_file.assert_not_awaited()
        service.list_folder.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_instructions_are_framed_as_user_context(self):
        part = await _provider(_service(), file_tools=False).get_prompt_part()

        assert part.startswith("## Project instructions")
        assert "Answer in French." in part
        assert "the instructions above win" in part
        assert "## Project files" not in part

    @pytest.mark.asyncio
    async def test_instructions_read_from_project_md(self):
        service = _service()

        await _provider(service).get_prompt_part()

        service.download_file.assert_awaited_once_with("projects/b/My%20Project/files/PROJECT.md")

    @pytest.mark.parametrize("instructions", [None, "", "   \n", "---\nname: x\n---\n\n"])
    @pytest.mark.asyncio
    async def test_missing_or_empty_instructions_add_no_section(self, instructions):
        part = await _provider(_service(instructions), file_tools=False).get_prompt_part()

        assert part == ""

    @pytest.mark.asyncio
    async def test_long_instructions_are_capped_with_a_note(self):
        body = "a" * (MAX_INSTRUCTIONS_CHARS + 10)

        part = await _provider(_service(body), file_tools=False).get_prompt_part()

        assert "a" * MAX_INSTRUCTIONS_CHARS in part
        assert "a" * (MAX_INSTRUCTIONS_CHARS + 1) not in part
        assert f"the first {MAX_INSTRUCTIONS_CHARS} of {MAX_INSTRUCTIONS_CHARS + 10}" in part

    @pytest.mark.asyncio
    async def test_files_section_names_the_working_folder_and_lists_context(self):
        service = _service(
            context=[
                _file("tickets.csv"),
                FolderEntry(url=f"{CONTEXT}sub/", is_folder=True, size=None),
                _file("sub/notes.md"),
            ]
        )

        part = await _provider(service).get_prompt_part()

        assert "## Project files" in part
        assert "`projects/b/My%20Project/files/artifacts/`" in part
        assert "holds files from earlier chats" in part
        assert "read-only" in part
        assert f"- {CONTEXT}tickets.csv" in part
        assert f"- {CONTEXT}sub/notes.md" in part
        assert f"- {CONTEXT}sub/\n" not in part
        service.list_folder.assert_awaited_once()
        assert service.list_folder.await_args.args == (CONTEXT,)
        assert service.list_folder.await_args.kwargs["max_depth"] > 1

    @pytest.mark.asyncio
    async def test_files_section_without_context_files_still_names_the_folder(self):
        part = await _provider(_service(instructions=None)).get_prompt_part()

        assert part.startswith("## Project files")
        assert "context files" not in part

    @pytest.mark.asyncio
    async def test_context_listing_is_capped(self):
        extra = 7
        files = [_file(f"f{i:03}.md") for i in range(MAX_CONTEXT_ENTRIES + extra)]

        part = await _provider(_service(context=files)).get_prompt_part()

        assert sum(line.startswith(f"- {CONTEXT}") for line in part.splitlines()) == (
            MAX_CONTEXT_ENTRIES
        )
        assert f"- and {extra} more" in part

    @pytest.mark.asyncio
    async def test_no_file_tools_no_files_section(self):
        service = _service(context=[_file("tickets.csv")])

        part = await _provider(service, file_tools=False).get_prompt_part()

        assert "## Project files" not in part
        service.list_folder.assert_not_awaited()


class TestStripFrontmatter:
    def test_frontmatter_is_stripped(self):
        assert strip_frontmatter("---\nname: p\ncolor: red\n---\nBody\n") == "Body\n"

    def test_no_frontmatter_keeps_the_file(self):
        assert strip_frontmatter("Body\n---\nmore") == "Body\n---\nmore"

    def test_empty_frontmatter_is_stripped(self):
        assert strip_frontmatter("---\n\n---\nBody") == "Body"

    @pytest.mark.parametrize(
        "content",
        [
            "---\nname: p\nBody without a closing fence",
            "---\nname: [unclosed\n---\nBody",
            "---\n- a list\n---\nBody",
        ],
    )
    def test_malformed_frontmatter_keeps_the_whole_file(self, content):
        assert strip_frontmatter(content) == content

    def test_frontmatter_after_a_bom_is_stripped(self):
        assert strip_frontmatter("\ufeff---\nname: p\n---\nBody") == "Body"
