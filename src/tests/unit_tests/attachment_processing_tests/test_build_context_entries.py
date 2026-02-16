from quickapp.attachment_processing._context_entries import (
    ContextEntry,
    ContextEntryStatus,
    build_context_entries,
)
from quickapp.config.context import Context, FileContextConfig, UserDefinedContextConfig


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
            FileContextConfig(url="files/bucket/a.csv"),
            UserDefinedContextConfig(content="more text"),
        ]
        urls, entries = build_context_entries(contexts, {})
        assert urls == {"files/bucket/a.csv"}
        assert len(entries) == 1
        assert entries[0].url == "files/bucket/a.csv"

    def test_new_entry_when_not_seen(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/data.csv")]
        urls, entries = build_context_entries(contexts, {})
        assert entries[0].status == ContextEntryStatus.new
        assert entries[0].title == "data.csv"
        assert entries[0].type == "text/csv"
        assert entries[0].url == "files/bucket/data.csv"

    def test_unchanged_entry_has_no_status(self):
        contexts: list[Context] = [FileContextConfig(url="files/bucket/data.csv")]
        seen = {
            "files/bucket/data.csv": ContextEntry(
                title="data.csv", url="files/bucket/data.csv", type="text/csv"
            )
        }
        _, entries = build_context_entries(contexts, seen)
        assert entries[0].status is None

    def test_updated_when_description_changes(self):
        contexts: list[Context] = [
            FileContextConfig(url="files/bucket/data.csv", description="V2 description")
        ]
        seen = {
            "files/bucket/data.csv": ContextEntry(
                title="data.csv",
                url="files/bucket/data.csv",
                type="text/csv",
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
            "files/bucket/old.csv": ContextEntry(
                title="old.csv",
                url="files/bucket/old.csv",
                type="text/csv",
                description="old desc",
            )
        }
        urls, entries = build_context_entries(contexts, seen)
        assert urls == set()
        assert len(entries) == 1
        assert entries[0].status == ContextEntryStatus.removed
        assert entries[0].url == "files/bucket/old.csv"
        assert entries[0].title == "old.csv"
        assert entries[0].description == "old desc"

    def test_duplicate_urls_deduplicated(self):
        contexts: list[Context] = [
            FileContextConfig(url="files/bucket/a.csv"),
            FileContextConfig(url="files/bucket/a.csv"),
        ]
        urls, entries = build_context_entries(contexts, {})
        assert urls == {"files/bucket/a.csv"}
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
        contexts: list[Context] = [FileContextConfig(url="files/bucket/a.csv")]
        _, entries = build_context_entries(contexts, {})
        assert entries[0].description is None

    def test_description_preserved_when_set(self):
        contexts: list[Context] = [
            FileContextConfig(url="files/bucket/a.csv", description="Reference data")
        ]
        _, entries = build_context_entries(contexts, {})
        assert entries[0].description == "Reference data"

    def test_mixed_new_unchanged_and_removed(self):
        contexts: list[Context] = [
            FileContextConfig(url="files/bucket/kept.csv"),
            FileContextConfig(url="files/bucket/new.pdf"),
        ]
        seen = {
            "files/bucket/kept.csv": ContextEntry(
                title="kept.csv", url="files/bucket/kept.csv", type="text/csv"
            ),
            "files/bucket/gone.txt": ContextEntry(
                title="gone.txt", url="files/bucket/gone.txt", type="text/plain"
            ),
        }
        urls, entries = build_context_entries(contexts, seen)
        assert urls == {"files/bucket/kept.csv", "files/bucket/new.pdf"}

        by_url = {e.url: e for e in entries}
        assert by_url["files/bucket/kept.csv"].status is None
        assert by_url["files/bucket/new.pdf"].status == ContextEntryStatus.new
        assert by_url["files/bucket/gone.txt"].status == ContextEntryStatus.removed