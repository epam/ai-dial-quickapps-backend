import pytest

from quickapp.common.file_reference_pattern import strip_file_prefix, to_file_url_reference


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
