import base64

import pytest

from quickapp.common.data_uri import collapse_data_uri_for_log, is_data_uri, parse_data_uri

PAYLOAD = b"%PDF-1.7 hello"
ENCODED = base64.b64encode(PAYLOAD).decode()


class TestIsDataUri:
    @pytest.mark.parametrize(
        "value",
        [
            "data:application/pdf;base64,AAAA",
            "DATA:text/plain,hello",
            "data:,",
        ],
    )
    def test_recognised(self, value):
        assert is_data_uri(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "files/bucket/foo.pdf",
            "https://example.com/data:application/pdf;base64,AAAA",
            "file:data::files/bucket/foo.pdf",
        ],
    )
    def test_not_recognised(self, value):
        assert is_data_uri(value) is False


class TestParseDataUri:
    def test_base64_payload(self):
        parsed = parse_data_uri(f"data:application/pdf;base64,{ENCODED}")
        assert parsed.media_type == "application/pdf"
        assert parsed.data == PAYLOAD

    def test_percent_encoded_payload(self):
        parsed = parse_data_uri("data:text/plain,hello%20world")
        assert parsed.media_type == "text/plain"
        assert parsed.data == b"hello world"

    def test_absent_media_type_defaults_to_text_plain(self):
        parsed = parse_data_uri("data:,hello")
        assert parsed.media_type == "text/plain"
        assert parsed.data == b"hello"

    def test_media_type_is_lowercased_and_parameters_dropped(self):
        parsed = parse_data_uri("data:TEXT/CSV;charset=utf-8;base64,aGk=")
        assert parsed.media_type == "text/csv"
        assert parsed.data == b"hi"

    def test_base64_marker_is_case_insensitive(self):
        assert parse_data_uri("data:text/plain;BASE64,aGk=").data == b"hi"

    def test_missing_comma_rejected(self):
        with pytest.raises(ValueError, match="payload separator"):
            parse_data_uri("data:application/pdf;base64")

    def test_invalid_base64_rejected(self):
        with pytest.raises(ValueError, match="base64 payload"):
            parse_data_uri("data:application/pdf;base64,not!valid!base64")

    def test_non_data_uri_rejected(self):
        with pytest.raises(ValueError, match="Not a data: URI"):
            parse_data_uri("files/bucket/foo.pdf")

    def test_error_messages_never_carry_the_payload(self):
        """Malformed-URI messages are handed back to the model; a payload in one is
        exactly what blew the context window in the original bug."""
        with pytest.raises(ValueError) as exc_info:
            parse_data_uri(f"data:application/pdf;base64,{ENCODED}!!!")
        assert ENCODED not in str(exc_info.value)


class TestCollapseDataUriForLog:
    def test_payload_replaced_by_its_size(self):
        collapsed = collapse_data_uri_for_log(f"data:application/pdf;base64,{ENCODED}")
        assert collapsed == f"data:application/pdf;base64,<elided {len(ENCODED)} chars>"
        assert ENCODED not in collapsed

    def test_absent_media_type(self):
        assert collapse_data_uri_for_log("data:,hello") == "data:,<elided 5 chars>"

    def test_metadata_without_separator_is_truncated_not_echoed(self):
        collapsed = collapse_data_uri_for_log("data:" + "A" * 5000)
        assert len(collapsed) < 200
        assert collapsed.endswith("...,<elided 0 chars>")
