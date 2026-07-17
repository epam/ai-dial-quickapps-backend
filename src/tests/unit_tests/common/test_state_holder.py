from unittest.mock import MagicMock

from quickapp.common.state_holder import StateHolder


class TestFileCacheKeyNormalization:
    def test_encoded_and_decoded_spellings_share_one_entry(self):
        holder = StateHolder()
        metadata = MagicMock()

        holder.store_file_data("files/b/file name (1).pdf", b"data", metadata)

        assert holder.get_file_data(url="files/b/file%20name%20%281%29.pdf") == b"data"
        assert holder.get_file_metadata("files/b/file%20name%20%281%29.pdf") is metadata

    def test_invalidate_accepts_either_spelling(self):
        holder = StateHolder()

        holder.store_file_data("files/b/file name.pdf", b"data")
        holder.invalidate_file_data("files/b/file%20name.pdf")

        assert holder.get_file_data(url="files/b/file name.pdf") is None

    def test_distinct_urls_keep_distinct_entries(self):
        holder = StateHolder()

        holder.store_file_data("files/b/a.txt", b"a")
        holder.store_file_data("files/b/b.txt", b"b")

        assert holder.get_file_data(url="files/b/a.txt") == b"a"
        assert holder.get_file_data(url="files/b/b.txt") == b"b"
