from quickapp.common.url_sanitization import _MAX_SANITIZED_URL_CHARS, sanitize_url_for_log

# DIAL's own cap on a resource id, restated here so this test documents the requirement
# ("no legal reference is ever truncated") without reaching into another module's privates.
_MAX_DIAL_REFERENCE_BYTES = 1024


class TestSanitizeUrlForLog:
    def test_strips_query_string_and_fragment(self):
        url = "https://host.example.com/path/to/file.pdf?sig=SECRET&exp=123#frag"
        assert sanitize_url_for_log(url) == "https://host.example.com/path/to/file.pdf"

    def test_strips_userinfo(self):
        url = "https://user:password@host.example.com/path?token=x"
        assert sanitize_url_for_log(url) == "https://host.example.com/path"

    def test_preserves_port(self):
        url = "https://host.example.com:8443/path?q=1"
        assert sanitize_url_for_log(url) == "https://host.example.com:8443/path"

    def test_relative_dial_path_preserved_without_query(self):
        assert sanitize_url_for_log("files/bucket/foo.pdf?token=x") == "files/bucket/foo.pdf"

    def test_relative_dial_path_without_query_unchanged(self):
        assert sanitize_url_for_log("files/bucket/foo.pdf") == "files/bucket/foo.pdf"

    def test_empty_string_returned_as_is(self):
        assert sanitize_url_for_log("") == ""


class TestSanitizeUrlForLogSize:
    """Issue #527: an echoed data: URI put the whole file into a log line and, via the
    tool-retry instruction, into the next model request."""

    def test_data_uri_payload_is_collapsed_to_a_size(self):
        url = "data:application/pdf;base64," + "A" * 1_000_000
        assert sanitize_url_for_log(url) == "data:application/pdf;base64,<1000000 chars>"

    def test_data_uri_without_payload_separator_is_truncated(self):
        url = "data:" + "A" * 1_000_000
        result = sanitize_url_for_log(url)
        assert len(result) < _MAX_SANITIZED_URL_CHARS + 100
        assert result.startswith("data:AAA")
        assert "truncated" in result

    def test_data_uri_scheme_match_is_case_insensitive(self):
        assert (
            sanitize_url_for_log("DATA:text/plain;base64,QUJD")
            == "DATA:text/plain;base64,<4 chars>"
        )

    def test_long_http_url_is_truncated(self):
        url = "https://host.example.com/" + "segment/" * 200
        result = sanitize_url_for_log(url)
        assert len(result) < len(url)
        assert result.startswith("https://host.example.com/segment/")
        assert result.endswith(
            f"[truncated, {len('https://host.example.com/' + 'segment/' * 200)} chars total]"
        )

    def test_url_at_the_cap_is_left_alone(self):
        path = "a" * (_MAX_SANITIZED_URL_CHARS - len("https://h/"))
        url = f"https://h/{path}"
        assert len(url) == _MAX_SANITIZED_URL_CHARS
        assert sanitize_url_for_log(url) == url

    def test_short_urls_are_unaffected(self):
        assert sanitize_url_for_log("files/bucket/foo.pdf") == "files/bucket/foo.pdf"

    def test_maximum_length_dial_reference_survives_intact(self):
        """No legal DIAL resource id is ever cut — truncating from the right would drop
        the filename, the part a log reader actually needs."""
        bucket = "b" * 64
        filler = "d" * (_MAX_DIAL_REFERENCE_BYTES - len(f"files/{bucket}//report.pdf"))
        path = f"files/{bucket}/{filler}/report.pdf"
        assert len(path.encode("utf-8")) == _MAX_DIAL_REFERENCE_BYTES
        assert sanitize_url_for_log(path) == path
        assert path.endswith("report.pdf")
