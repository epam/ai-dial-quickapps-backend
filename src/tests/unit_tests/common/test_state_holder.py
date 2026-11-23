from quickapp.common.state_holder import StateHolder

_ENCODED = "projects/b/My%20P/files/artifacts/Q1%20(draft).md"
_DECODED = "projects/b/My P/files/artifacts/Q1 (draft).md"


class TestFileCache:
    def test_entry_found_by_either_spelling(self):
        holder = StateHolder()
        holder.store_file_data(_ENCODED, b"data", content_type="text/markdown")

        assert holder.get_file_data(url=_DECODED) == b"data"
        assert holder.get_content_type(_DECODED) == "text/markdown"

    def test_invalidated_by_either_spelling(self):
        holder = StateHolder()
        holder.store_file_data(_DECODED, b"data")

        holder.invalidate_file_data(_ENCODED)

        assert holder.get_file_data(url=_DECODED) is None

    def test_external_url_kept_as_is(self):
        holder = StateHolder()
        holder.store_file_data("https://example.com/a%20b.pdf?x=1", b"data")

        assert holder.get_file_data(url="https://example.com/a%20b.pdf?x=1") == b"data"
        assert holder.get_file_data(url="https://example.com/a b.pdf?x=1") is None
