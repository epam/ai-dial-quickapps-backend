from quickapp.common.url_sanitization import sanitize_url_for_log, sanitize_url_for_message


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


class TestSanitizeUrlForMessage:
    def test_strips_secrets_like_log_sanitizer(self):
        url = "https://user:pass@host.example.com/path?sig=SECRET#frag"
        assert sanitize_url_for_message(url) == "https://host.example.com/path"

    def test_empty_string_returned_as_is(self):
        assert sanitize_url_for_message("") == ""

    def test_short_data_uri_collapsed_to_header_and_size(self):
        url = "data:application/pdf;base64,JVBERi0xLjQ="
        assert sanitize_url_for_message(url) == "data:application/pdf;base64,<12 chars>"

    def test_oversized_data_uri_payload_dropped(self):
        payload = "A" * 1_389_572
        result = sanitize_url_for_message(f"data:application/pdf;base64,{payload}")
        assert result == "data:application/pdf;base64,<1389572 chars>"
        assert len(result) < 200

    def test_data_scheme_detection_is_case_insensitive(self):
        assert sanitize_url_for_message("DATA:text/plain,hello") == "data:text/plain,<5 chars>"

    def test_malformed_data_uri_without_comma_falls_back(self):
        # No comma: not collapsed, but still bounded by the generic truncation cap.
        blob = "x" * 500
        result = sanitize_url_for_message(f"data:{blob}")
        assert result.startswith(f"data:{'x' * 100}")
        assert result.endswith("…(truncated, 505 chars)")

    def test_long_non_data_url_truncated_with_marker(self):
        url = "https://host.example.com/" + "p" * 500
        result = sanitize_url_for_message(url)
        assert len(result) == 200 + len("…(truncated, 525 chars)")
        assert result.endswith("…(truncated, 525 chars)")
        assert result.startswith("https://host.example.com/")

    def test_value_within_budget_untouched(self):
        url = "https://host.example.com/reports/q3.pdf"
        assert sanitize_url_for_message(url) == url

    def test_custom_max_length_honoured(self):
        assert sanitize_url_for_message("abcdefghij", max_length=4) == "abcd…(truncated, 10 chars)"
