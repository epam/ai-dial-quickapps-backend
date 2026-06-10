import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.attachment_processing._context_entries import (
    ContextEntry,
    ContextEntryStatus,
    build_context_entries,
    build_context_entries_async,
)
from quickapp.attachment_processing._expanded_context_file_urls import ExpandedContextFileUrls
from quickapp.common.abstract.folder_listing_provider import (
    ExpandedFolderEntry,
    FolderListingProvider,
)
from quickapp.common.attachment_processing_utils import collect_get_content_allowed_urls
from quickapp.common.folder_context_urls import FOLDER_METADATA_MIME
from quickapp.config.context import (
    Context,
    FileContextConfig,
    FolderContextConfig,
    UserDefinedContextConfig,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._gating import (
    should_enable_get_content_tool,
)


class TestBuildContextEntries:
    def test_empty_contexts_returns_empty(self):
        contexts: list[Context] = []
        urls, entries = build_context_entries(contexts, {})
        assert urls == set()
        assert entries == []

    def test_non_file_contexts_skipped(self):
        contexts: list[Context] = [UserDefinedContextConfig(content="some text")]
        urls, entries = build_context_entries(contexts, {})
        assert urls == set()
        assert entries == []

    def test_mixed_context_types_only_file_included(self):
        contexts: list[Context] = [
            UserDefinedContextConfig(content="text"),
            FileContextConfig(url="files/bucket/a.pdf"),
            UserDefinedContextConfig(content="more text"),
        ]
        urls, entries = build_context_entries(contexts, {})
        assert urls == {"files/bucket/a.pdf"}
        assert len(entries) == 1
        assert entries[0].url == "files/bucket/a.pdf"

    def test_new_entry_when_not_seen(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/data.pdf")]
        urls, entries = build_context_entries(contexts, {})
        assert entries[0].status == ContextEntryStatus.new
        assert entries[0].title == "data.pdf"
        assert entries[0].type == "application/pdf"
        assert entries[0].url == "files/bucket/data.pdf"

    def test_unchanged_entry_has_no_status(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/data.pdf")]
        seen = {
            "files/bucket/data.pdf": ContextEntry(
                title="data.pdf", url="files/bucket/data.pdf", type="application/pdf"
            )
        }
        _, entries = build_context_entries(contexts, seen)
        assert entries[0].status is None

    def test_updated_when_description_changes(self):
        contexts: list[Context] = [
            FileContextConfig(url="files/bucket/data.pdf", description="V2 description")
        ]
        seen = {
            "files/bucket/data.pdf": ContextEntry(
                title="data.pdf",
                url="files/bucket/data.pdf",
                type="application/pdf",
                description="V1 description",
            )
        }
        _, entries = build_context_entries(contexts, seen)
        assert entries[0].status == ContextEntryStatus.updated
        assert entries[0].description == "V2 description"

    def test_updated_when_type_changes(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/data.json")]
        seen = {
            "files/bucket/data.json": ContextEntry(
                title="data.json",
                url="files/bucket/data.json",
                type="text/plain",  # wrong type from before
            )
        }
        _, entries = build_context_entries(contexts, seen)
        assert entries[0].status == ContextEntryStatus.updated

    def test_removed_entry_for_missing_url(self):
        contexts: list[Context] = []
        seen = {
            "files/bucket/old.pdf": ContextEntry(
                title="old.pdf",
                url="files/bucket/old.pdf",
                type="application/pdf",
                description="old desc",
            )
        }
        urls, entries = build_context_entries(contexts, seen)
        assert urls == set()
        assert len(entries) == 1
        assert entries[0].status == ContextEntryStatus.removed
        assert entries[0].url == "files/bucket/old.pdf"
        assert entries[0].title == "old.pdf"
        assert entries[0].description == "old desc"

    def test_duplicate_urls_deduplicated(self):
        contexts: list[Context] = [
            FileContextConfig(url="files/bucket/a.pdf"),
            FileContextConfig(url="files/bucket/a.pdf"),
        ]
        urls, entries = build_context_entries(contexts, {})
        assert urls == {"files/bucket/a.pdf"}
        assert len(entries) == 1

    def test_mime_type_guessed_from_filename(self):
        contexts: list[Context] = [
            FileContextConfig(url="files/bucket/report.pdf"),
            FileContextConfig(url="files/bucket/image.png"),
        ]
        _, entries = build_context_entries(contexts, {})
        assert entries[0].type == "application/pdf"
        assert entries[1].type == "image/png"

    def test_unknown_extension_gives_empty_type(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/data.xyz123")]
        _, entries = build_context_entries(contexts, {})
        assert entries[0].type == ""

    def test_title_extracted_from_url(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/subdir/report.pdf")]
        _, entries = build_context_entries(contexts, {})
        assert entries[0].title == "report.pdf"

    def test_description_none_when_not_set(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/a.pdf")]
        _, entries = build_context_entries(contexts, {})
        assert entries[0].description is None

    def test_description_preserved_when_set(self):
        contexts: list[Context] = [
            FileContextConfig(url="files/bucket/a.pdf", description="Reference data")
        ]
        _, entries = build_context_entries(contexts, {})
        assert entries[0].description == "Reference data"

    def test_mixed_new_unchanged_and_removed(self):
        contexts: list[Context] = [
            FileContextConfig(url="files/bucket/kept.pdf"),
            FileContextConfig(url="files/bucket/new.pdf"),
        ]
        seen = {
            "files/bucket/kept.pdf": ContextEntry(
                title="kept.pdf", url="files/bucket/kept.pdf", type="application/pdf"
            ),
            "files/bucket/gone.txt": ContextEntry(
                title="gone.txt", url="files/bucket/gone.txt", type="text/plain"
            ),
        }
        urls, entries = build_context_entries(contexts, seen)
        assert urls == {"files/bucket/kept.pdf", "files/bucket/new.pdf"}

        by_url = {e.url: e for e in entries}
        assert by_url["files/bucket/kept.pdf"].status is None
        assert by_url["files/bucket/new.pdf"].status == ContextEntryStatus.new
        assert by_url["files/bucket/gone.txt"].status == ContextEntryStatus.removed


class TestShouldGetContentTool:
    def test_true_when_pdf_context_and_deployment_accepts_pdf(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/a.pdf")]
        assert should_enable_get_content_tool(contexts, [], ["application/pdf"]) is True

    def test_true_when_non_pdf_inferred_and_deployment_accepts_that_mime(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/readme.txt")]
        assert should_enable_get_content_tool(contexts, [], ["text/plain"]) is True

    def test_false_when_inferred_mime_not_accepted_by_deployment(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/readme.txt")]
        assert should_enable_get_content_tool(contexts, [], ["application/pdf"]) is False

    def test_false_when_deployment_excludes_file_mime(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/a.pdf")]
        assert should_enable_get_content_tool(contexts, [], ["image/*"]) is False

    def test_false_when_input_attachment_types_none(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/a.pdf")]
        assert should_enable_get_content_tool(contexts, [], None) is False

    def test_false_when_input_attachment_types_empty(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/a.pdf")]
        assert should_enable_get_content_tool(contexts, [], []) is False


class TestGetContentEligibility:
    def test_enable_get_content_when_user_attachment_supported(self):
        contexts: list[Context] = []
        messages = [
            Message(
                role=Role.USER,
                content="use this",
                custom_content=CustomContent(
                    attachments=[
                        Attachment(
                            title="report.pdf",
                            url="files/bucket/user-report.pdf",
                            type="application/pdf",
                        )
                    ]
                ),
            )
        ]
        assert (
            should_enable_get_content_tool(
                contexts=contexts,
                messages=messages,
                input_attachment_types=["application/pdf"],
            )
            is True
        )

    def test_collect_allowed_urls_includes_supported_user_attachment(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/admin.pdf")]
        messages = [
            Message(
                role=Role.USER,
                content="attached",
                custom_content=CustomContent(
                    attachments=[
                        Attachment(
                            title="notes.txt",
                            url="files/bucket/notes.txt",
                            type="text/plain",
                        ),
                        Attachment(
                            title="report.pdf",
                            url="files/bucket/user-report.pdf",
                            type="application/pdf",
                        ),
                    ]
                ),
            )
        ]
        allowed = collect_get_content_allowed_urls(
            contexts=contexts,
            messages=messages,
            input_attachment_types=["application/pdf"],
        )
        assert "files/bucket/admin.pdf" in allowed
        assert "files/bucket/user-report.pdf" in allowed
        assert "files/bucket/notes.txt" not in allowed


class _FakeFolderListing(FolderListingProvider):
    def __init__(self, entries: list[ExpandedFolderEntry]) -> None:
        self._entries = entries

    async def list_folder_entries(
        self, files_folder_url: str, *, max_depth: int
    ) -> list[ExpandedFolderEntry]:
        return self._entries


class TestBuildContextEntriesAsync:
    @pytest.mark.asyncio
    async def test_expands_folder_with_files_and_subfolders(self):
        contexts: list[Context] = [
            FolderContextConfig(
                url="metadata/files/bucket/shared-docs/",
                description="Shared docs",
            )
        ]
        listing = _FakeFolderListing(
            [
                ExpandedFolderEntry(url="files/bucket/shared-docs/sub/", is_folder=True),
                ExpandedFolderEntry(url="files/bucket/shared-docs/a.pdf", is_folder=False),
            ]
        )
        holder = ExpandedContextFileUrls()
        urls, entries = await build_context_entries_async(contexts, {}, listing, holder)

        assert urls == {
            "metadata/files/bucket/shared-docs/",
            "files/bucket/shared-docs/sub/",
            "files/bucket/shared-docs/a.pdf",
        }
        assert holder.urls == {"files/bucket/shared-docs/a.pdf"}
        by_url = {e.url: e for e in entries}
        assert by_url["metadata/files/bucket/shared-docs/"].type == FOLDER_METADATA_MIME
        assert by_url["metadata/files/bucket/shared-docs/"].description == "Shared docs"
        assert by_url["files/bucket/shared-docs/sub/"].type == FOLDER_METADATA_MIME
        assert by_url["files/bucket/shared-docs/a.pdf"].type == "application/pdf"

    @pytest.mark.asyncio
    async def test_new_file_in_folder_gets_new_status(self):
        contexts: list[Context] = [
            FolderContextConfig(url="metadata/files/bucket/docs/"),
        ]
        listing = _FakeFolderListing(
            [ExpandedFolderEntry(url="files/bucket/docs/new.pdf", is_folder=False)]
        )
        seen = {
            "metadata/files/bucket/docs/": ContextEntry(
                title="docs",
                url="metadata/files/bucket/docs/",
                type=FOLDER_METADATA_MIME,
            )
        }
        _, entries = await build_context_entries_async(contexts, seen, listing, None)
        by_url = {e.url: e for e in entries}
        assert by_url["files/bucket/docs/new.pdf"].status == ContextEntryStatus.new

    @pytest.mark.asyncio
    async def test_collect_allowed_urls_includes_expanded_folder_file(self):
        contexts: list[Context] = [
            FolderContextConfig(url="metadata/files/bucket/docs/"),
        ]
        expanded = {"files/bucket/docs/report.pdf"}
        allowed = collect_get_content_allowed_urls(
            contexts=contexts,
            messages=[],
            input_attachment_types=["application/pdf"],
            expanded_folder_file_urls=expanded,
        )
        assert "files/bucket/docs/report.pdf" in allowed
