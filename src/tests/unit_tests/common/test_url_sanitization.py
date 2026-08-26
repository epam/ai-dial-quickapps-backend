import base64

from quickapp.common.url_sanitization import sanitize_url_for_log


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

    def test_data_uri_payload_is_elided(self):
        """``urlsplit`` parks a data: URI's whole payload in ``.path``; without a
        dedicated branch the sanitizer would hand it straight back (the original
        context-window bug)."""
        payload = base64.b64encode(b"x" * 4096).decode()
        sanitized = sanitize_url_for_log(f"data:application/pdf;base64,{payload}")

        assert payload not in sanitized
        assert sanitized == f"data:application/pdf;base64,<elided {len(payload)} chars>"

    def test_data_uri_detection_is_case_insensitive(self):
        assert sanitize_url_for_log("DATA:text/plain,hello") == "data:text/plain,<elided 5 chars>"

    def test_url_merely_containing_data_colon_is_not_collapsed(self):
        url = "https://host.example.com/data:application/pdf"
        assert sanitize_url_for_log(url) == url
