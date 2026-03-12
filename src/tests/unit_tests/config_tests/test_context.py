"""Unit tests for context config: file/user-defined discriminator and .dial_folder convention."""

import pytest
from pydantic import TypeAdapter, ValidationError

from quickapp.config.context import (
    DIAL_FOLDER_PLACEHOLDER,
    Context,
    FileContextConfig,
    UserDefinedContextConfig,
    get_folder_path_from_file_url,
)

_context_adapter = TypeAdapter(Context)


class TestGetFolderPathFromFileUrl:
    """Folder placeholder: url ending with /.dial_folder yields folder path."""

    def test_returns_folder_path_when_placeholder_suffix(self):
        assert get_folder_path_from_file_url(
            "files/bucket/testFolder/.dial_folder"
        ) == "files/bucket/testFolder"
        assert get_folder_path_from_file_url(
            "files/684f6Lz7ubje66aoCRsa5c/testFolder/.dial_folder"
        ) == "files/684f6Lz7ubje66aoCRsa5c/testFolder"

    def test_returns_none_when_not_placeholder(self):
        assert get_folder_path_from_file_url("files/bucket/a.pdf") is None
        assert get_folder_path_from_file_url("files/bucket/folder") is None
        assert get_folder_path_from_file_url("") is None

    def test_returns_none_when_only_placeholder(self):
        assert get_folder_path_from_file_url("/.dial_folder") is None  # empty path after strip

    def test_placeholder_constant(self):
        assert DIAL_FOLDER_PLACEHOLDER == "/.dial_folder"


class TestFileContextConfig:
    """FileContextConfig parsing (including folder placeholder URLs from UI)."""

    def test_parses_file_url(self):
        cfg = FileContextConfig(url="files/bucket/a.pdf")
        assert cfg.type == "file"
        assert cfg.url == "files/bucket/a.pdf"
        assert cfg.description is None

    def test_parses_folder_placeholder_url_from_ui(self):
        """UI sends type 'file' with url ending in /.dial_folder for folders."""
        cfg = FileContextConfig(
            url="files/684f6Lz7ubje66aoCRsa5c/testFolder/.dial_folder"
        )
        assert cfg.type == "file"
        assert cfg.url == "files/684f6Lz7ubje66aoCRsa5c/testFolder/.dial_folder"
        assert get_folder_path_from_file_url(cfg.url) == "files/684f6Lz7ubje66aoCRsa5c/testFolder"


class TestContextDiscriminator:
    """Context union discriminator: file | user-defined (no folder type; folder = file + .dial_folder)."""

    def test_file_context_roundtrip(self):
        data = {"type": "file", "url": "files/bucket/a.pdf"}
        ctx = _context_adapter.validate_python(data)
        assert isinstance(ctx, FileContextConfig)
        assert ctx.url == "files/bucket/a.pdf"

    def test_file_context_with_dial_folder_roundtrip(self):
        data = {
            "type": "file",
            "url": "files/684f6Lz7ubje66aoCRsa5c/testFolder/.dial_folder",
        }
        ctx = _context_adapter.validate_python(data)
        assert isinstance(ctx, FileContextConfig)
        assert ctx.url == "files/684f6Lz7ubje66aoCRsa5c/testFolder/.dial_folder"

    def test_user_defined_context_roundtrip(self):
        data = {"type": "user-defined", "content": "Some text"}
        ctx = _context_adapter.validate_python(data)
        assert isinstance(ctx, UserDefinedContextConfig)
        assert ctx.content == "Some text"

    def test_discriminator_required(self):
        with pytest.raises(ValidationError):
            _context_adapter.validate_python({"url": "files/bucket/x"})

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            _context_adapter.validate_python({"type": "unknown", "url": "files/bucket/x"})
