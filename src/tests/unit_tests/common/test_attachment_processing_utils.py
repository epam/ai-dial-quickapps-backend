from quickapp.common.attachment_processing_utils import normalize_attachment_url_argument


class TestNormalizeAttachmentUrlArgument:
    def test_strips_outer_whitespace(self):
        assert normalize_attachment_url_argument("  files/bucket/a.pdf  ") == "files/bucket/a.pdf"

    def test_strips_single_leading_slash(self):
        assert normalize_attachment_url_argument("/files/bucket/a.pdf") == "files/bucket/a.pdf"

    def test_strips_leading_slash_after_whitespace(self):
        assert normalize_attachment_url_argument("  /files/bucket/a.pdf") == "files/bucket/a.pdf"

    def test_preserves_double_slash(self):
        assert normalize_attachment_url_argument("//files/bucket/a.pdf") == "//files/bucket/a.pdf"

    def test_handles_empty_string(self):
        assert normalize_attachment_url_argument("") == ""

    def test_handles_whitespace_only(self):
        assert normalize_attachment_url_argument("   ") == ""

    def test_handles_slash_only(self):
        assert normalize_attachment_url_argument("/") == ""

    def test_no_op_when_already_normalized(self):
        assert normalize_attachment_url_argument("files/bucket/a.pdf") == "files/bucket/a.pdf"
