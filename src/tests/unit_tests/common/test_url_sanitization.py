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
