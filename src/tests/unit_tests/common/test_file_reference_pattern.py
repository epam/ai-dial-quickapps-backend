import pytest

from quickapp.common.file_reference_pattern import (
    FILE_PATTERN,
    strip_file_prefix,
    to_file_url_reference,
)


class TestFilePattern:
    @pytest.mark.parametrize(
        "value,prefix,file_url",
        [
            ("file:data::files/doc.pdf", "data", "files/doc.pdf"),
            ("file:base64::files/doc.pdf", "base64", "files/doc.pdf"),
            ("file:text::files/doc.txt", "text", "files/doc.txt"),
            ("file:url::https://example.com/x", "url", "https://example.com/x"),
            ("//file:DATA::files/doc.pdf", "DATA", "files/doc.pdf"),
        ],
    )
    def test_matches_known_prefixes(self, value: str, prefix: str, file_url: str):
        match = FILE_PATTERN.match(value)
        assert match is not None
        assert match.group("prefix") == prefix
        assert match.group("file_url") == file_url


class TestToFileUrlReference:
    @pytest.mark.parametrize(
        "url",
        [
            "files/bucket/report.pdf",
            "/files/bucket/report.pdf",
            "https://example.com/report.pdf",
        ],
    )
    def test_wraps_with_file_url_prefix(self, url: str):
        assert to_file_url_reference(url) == f"file:url::{url}"

    @pytest.mark.parametrize(
        "url",
        [
            "files/bucket/report.pdf",
            "https://example.com/report.pdf",
        ],
    )
    def test_round_trips_with_strip_file_prefix(self, url: str):
        # to_file_url_reference is the inverse of strip_file_prefix for the url prefix.
        assert strip_file_prefix(to_file_url_reference(url)) == url


class TestPrefixlessFileReference:
    """FILE_PATTERN keeps the prefix marker optional so callers can detect and reject a
    prefix-less `file:` reference, but strip_file_prefix must not shorten one."""

    def test_prefixless_file_reference_not_stripped(self):
        assert strip_file_prefix("file:files/bucket/report.pdf") == "file:files/bucket/report.pdf"

    def test_path_ending_in_file_colon_segment_not_shortened(self):
        assert strip_file_prefix("files/bucket/notes.txt") == "files/bucket/notes.txt"

    def test_recognized_prefix_still_stripped(self):
        assert strip_file_prefix("file:url::files/bucket/report.pdf") == "files/bucket/report.pdf"
