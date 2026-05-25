import base64
from unittest.mock import AsyncMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.file_transfer._file_argument_transformer import _FileArgumentTransformer


@pytest.fixture
def mock_file_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def transformer(mock_file_service: AsyncMock) -> _FileArgumentTransformer:
    return _FileArgumentTransformer(file_service=mock_file_service)


class TestFileArgumentTransformer:
    @pytest.mark.asyncio
    async def test_base64_prefix(self, transformer, mock_file_service):
        raw = b"hello world"
        mock_file_service.download_file.return_value = (raw, None)
        result = await transformer.transform({"data": "file:base64::files/test.bin"})
        assert result["data"] == base64.b64encode(raw).decode()
        mock_file_service.download_file.assert_called_once_with("files/test.bin")

    @pytest.mark.asyncio
    async def test_text_prefix(self, transformer, mock_file_service):
        mock_file_service.download_file.return_value = (b"hello text", None)
        result = await transformer.transform({"content": "file:text::files/test.txt"})
        assert result["content"] == "hello text"

    @pytest.mark.asyncio
    async def test_url_prefix_passes_through(self, transformer, mock_file_service):
        result = await transformer.transform({"uri": "file:url::https://example.com/file.pdf"})
        assert result["uri"] == "https://example.com/file.pdf"
        mock_file_service.download_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_prefix_raises(self, transformer):
        with pytest.raises(InvalidToolCallParameterException):
            await transformer.transform({"data": "file:files/test.bin"})

    @pytest.mark.asyncio
    async def test_non_string_values_pass_through(self, transformer):
        result = await transformer.transform({"count": 42, "flag": True, "items": [1, 2]})
        assert result == {"count": 42, "flag": True, "items": [1, 2]}

    @pytest.mark.asyncio
    async def test_non_file_strings_pass_through(self, transformer):
        result = await transformer.transform({"query": "hello world", "name": "test"})
        assert result == {"query": "hello world", "name": "test"}

    @pytest.mark.asyncio
    async def test_multiple_file_params(self, transformer, mock_file_service):
        mock_file_service.download_file.return_value = (b"content", None)
        result = await transformer.transform(
            {
                "a": "file:text::files/a.txt",
                "b": "file:url::https://example.com/b.pdf",
                "c": "normal_value",
            }
        )
        assert result["a"] == "content"
        assert result["b"] == "https://example.com/b.pdf"
        assert result["c"] == "normal_value"

    @pytest.mark.asyncio
    async def test_case_insensitive_prefix(self, transformer, mock_file_service):
        mock_file_service.download_file.return_value = (b"data", None)
        result = await transformer.transform({"x": "file:TEXT::files/test.txt"})
        assert result["x"] == "data"

    @pytest.mark.asyncio
    async def test_leading_slashes_stripped(self, transformer, mock_file_service):
        result = await transformer.transform({"uri": "//file:url::https://example.com/f"})
        assert result["uri"] == "https://example.com/f"

    @pytest.mark.asyncio
    async def test_list_with_multiple_file_references(self, transformer, mock_file_service):
        mock_file_service.download_file.return_value = (b"content", None)
        result = await transformer.transform(
            {
                "docs": [
                    "file:base64::files/a.png",
                    "file:text::files/b.txt",
                    "file:url::https://example.com/c.pdf",
                ]
            }
        )
        assert result["docs"][0] == base64.b64encode(b"content").decode()
        assert result["docs"][1] == "content"
        assert result["docs"][2] == "https://example.com/c.pdf"

    @pytest.mark.asyncio
    async def test_list_with_mixed_file_and_plain_strings(self, transformer, mock_file_service):
        mock_file_service.download_file.return_value = (b"data", None)
        result = await transformer.transform(
            {"items": ["file:base64::files/img.png", "plain string", "another plain"]}
        )
        assert result["items"][0] == base64.b64encode(b"data").decode()
        assert result["items"][1] == "plain string"
        assert result["items"][2] == "another plain"

    @pytest.mark.asyncio
    async def test_list_with_non_string_elements(self, transformer):
        result = await transformer.transform({"mixed": [42, True, "plain", None]})
        assert result["mixed"] == [42, True, "plain", None]

    @pytest.mark.asyncio
    async def test_empty_list_passes_through(self, transformer):
        result = await transformer.transform({"items": []})
        assert result["items"] == []
