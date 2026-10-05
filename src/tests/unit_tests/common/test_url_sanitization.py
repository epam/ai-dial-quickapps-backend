from quickapp.common.url_sanitization import _MAX_URL_LENGTH, sanitize_url


class TestSanitizeUrl:
    def test_strips_query_string_and_fragment(self):
        url = "https://host.example.com/path/to/file.pdf?sig=SECRET&exp=123#frag"
        assert sanitize_url(url) == "https://host.example.com/path/to/file.pdf"

    def test_strips_userinfo(self):
        url = "https://user:password@host.example.com/path?token=x"
        assert sanitize_url(url) == "https://host.example.com/path"

    def test_preserves_port(self):
        url = "https://host.example.com:8443/path?q=1"
        assert sanitize_url(url) == "https://host.example.com:8443/path"

    def test_relative_dial_path_preserved_without_query(self):
        assert sanitize_url("files/bucket/foo.pdf?token=x") == "files/bucket/foo.pdf"

    def test_relative_dial_path_without_query_unchanged(self):
        assert sanitize_url("files/bucket/foo.pdf") == "files/bucket/foo.pdf"

    def test_empty_string_returned_as_is(self):
        assert sanitize_url("") == ""

    def test_value_within_budget_untouched(self):
        url = "https://host.example.com/reports/q3.pdf"
        assert sanitize_url(url) == url


class TestDataUri:
    def test_data_uri_collapsed_to_header(self):
        url = "data:application/pdf;base64,JVBERi0xLjQ="
        assert sanitize_url(url) == "data:application/pdf;base64,…"

    def test_oversized_data_uri_payload_dropped(self):
        payload = "A" * 1_389_572
        result = sanitize_url(f"data:application/pdf;base64,{payload}")
        assert result == "data:application/pdf;base64,…"

    def test_data_scheme_detection_is_case_insensitive(self):
        assert sanitize_url("DATA:text/plain,hello") == "data:text/plain,…"

    def test_malformed_data_uri_without_comma_falls_back(self):
        # No comma: not collapsed, but still bounded by the generic truncation cap.
        blob = "x" * 500
        result = sanitize_url(f"data:{blob}")
        assert result == f"data:{'x' * (_MAX_URL_LENGTH - len('data:'))}…"


class TestTruncation:
    def test_long_url_truncated_with_marker(self):
        url = "https://host.example.com/" + "p" * 500
        result = sanitize_url(url)
        assert len(result) == _MAX_URL_LENGTH + 1
        assert result.startswith("https://host.example.com/")
        assert result.endswith("…")
