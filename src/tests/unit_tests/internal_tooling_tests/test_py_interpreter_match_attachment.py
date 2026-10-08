from urllib.parse import unquote

from aidial_sdk.chat_completion import Attachment

from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.common.utils import posix_path_last_segment
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_tool import _PyInterpreterTool


def _attachment(url: str) -> Attachment:
    return Attachment(url=url)


class TestMatchAttachment:
    """_match_attachment strips file:*:: prefixes before comparing against conversation URLs."""

    def _map(self, *urls: str) -> dict[str, Attachment]:
        return {url: _attachment(url) for url in urls}

    def test_bare_path_matches(self):
        m = self._map("files/bucket/foo.pdf")
        url, att = _PyInterpreterTool._match_attachment("files/bucket/foo.pdf", m)
        assert url == "files/bucket/foo.pdf"
        assert att is not None

    def test_data_prefix_stripped_before_match(self):
        m = self._map("files/bucket/foo.pdf")
        url, att = _PyInterpreterTool._match_attachment("file:data::files/bucket/foo.pdf", m)
        assert url == "files/bucket/foo.pdf"
        assert att is not None

    def test_url_prefix_stripped_before_match(self):
        m = self._map("https://example.com/foo.pdf")
        url, att = _PyInterpreterTool._match_attachment("file:url::https://example.com/foo.pdf", m)
        assert url == "https://example.com/foo.pdf"
        assert att is not None

    def test_base64_prefix_stripped_before_match(self):
        m = self._map("files/bucket/foo.pdf")
        url, att = _PyInterpreterTool._match_attachment("file:base64::files/bucket/foo.pdf", m)
        assert url == "files/bucket/foo.pdf"
        assert att is not None

    def test_no_match_returns_none(self):
        m = self._map("files/bucket/other.pdf")
        url, att = _PyInterpreterTool._match_attachment("files/bucket/foo.pdf", m)
        assert url is None
        assert att is None


class TestPrepareInputFilesTargetPath:
    """_prepare_input_files computes the sandbox target_path the same way _match_attachment
    computes its bare name, so a prefixed reference with no '/' (e.g. `file:url::report.pdf`)
    doesn't produce a garbage target_path while the attachment still resolves correctly."""

    def test_target_path_matches_attachment_match_bare_name(self):
        file_name = "file:url::report.pdf"

        target_path = unquote(posix_path_last_segment(strip_file_prefix(file_name)))
        matched_url, matched_attachment = _PyInterpreterTool._match_attachment(
            file_name, {"report.pdf": _attachment("report.pdf")}
        )

        assert target_path == "report.pdf"
        assert matched_url == "report.pdf"
        assert matched_attachment is not None
