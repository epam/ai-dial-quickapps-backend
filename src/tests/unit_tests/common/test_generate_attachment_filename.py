from unittest.mock import patch

import pytest

from quickapp.common.utils import generate_attachment_filename, guess_attachment_extension

_OFFICE_MIME_EXTENSIONS = [
    (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    ("application/msword", ".doc"),
    ("application/vnd.ms-excel", ".xls"),
    ("application/vnd.ms-powerpoint", ".ppt"),
]


class TestGuessAttachmentExtension:

    def test_none_returns_empty(self):
        assert guess_attachment_extension(None) == ""

    def test_empty_string_returns_empty(self):
        assert guess_attachment_extension("") == ""

    def test_whitespace_only_returns_empty(self):
        assert guess_attachment_extension("   ") == ""

    def test_known_type_pdf(self):
        assert guess_attachment_extension("application/pdf") == ".pdf"

    def test_strips_content_type_parameters(self):
        assert guess_attachment_extension("application/pdf; charset=binary") == ".pdf"

    @pytest.mark.parametrize("mime_type,extension", _OFFICE_MIME_EXTENSIONS)
    def test_office_types_via_stdlib_or_fallback(self, mime_type: str, extension: str):
        assert guess_attachment_extension(mime_type) == extension

    @pytest.mark.parametrize("mime_type,extension", _OFFICE_MIME_EXTENSIONS)
    def test_office_fallback_when_guess_extension_returns_none(
        self, mime_type: str, extension: str
    ):
        # Simulate Alpine/slim images without /etc/mime.types.
        with patch("quickapp.common.utils.mimetypes.guess_extension", return_value=None):
            assert guess_attachment_extension(mime_type) == extension

    def test_unknown_type_returns_empty_when_guess_fails(self):
        with patch("quickapp.common.utils.mimetypes.guess_extension", return_value=None):
            assert guess_attachment_extension("application/x-unknown-custom") == ""

    def test_office_fallback_with_parameters_when_guess_fails(self):
        mime = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            "; charset=binary"
        )
        with patch("quickapp.common.utils.mimetypes.guess_extension", return_value=None):
            assert guess_attachment_extension(mime) == ".docx"


class TestGenerateAttachmentFilename:

    def test_none_mime_has_no_extension(self):
        name = generate_attachment_filename(None)
        assert name.startswith("quick-app-")
        assert not name.endswith(
            (".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".png")
        )

    def test_pdf_gets_extension(self):
        assert generate_attachment_filename("application/pdf").endswith(".pdf")

    def test_custom_base_filename(self):
        name = generate_attachment_filename("application/pdf", base_filename="my-tool")
        assert name.startswith("my-tool-")
        assert name.endswith(".pdf")

    @pytest.mark.parametrize("mime_type,extension", _OFFICE_MIME_EXTENSIONS)
    def test_office_mime_gets_extension(self, mime_type: str, extension: str):
        with patch("quickapp.common.utils.mimetypes.guess_extension", return_value=None):
            assert generate_attachment_filename(mime_type).endswith(extension)
