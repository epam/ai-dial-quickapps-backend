from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import DialException, EtagMismatchError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.shared.external_fetch.external_url_fetcher import FetchedBytes
from quickapp.shared.external_fetch.web_content_fetcher import WebContentFetcher
from quickapp.shared.home_path.home_path_resolver import HomePathResolver
from quickapp.web_tooling._tool_configs import WEB_FETCH_TOOL_CONFIG
from quickapp.web_tooling._web_fetch_tool import _WebFetchTool

_HOME = "files/appbucket/agent/"


def _make_tool(
    fetched: FetchedBytes | Exception | None = None,
    *,
    max_inline_size: int = 40_000,
    write_bytes_side_effect=None,
) -> tuple[_WebFetchTool, MagicMock]:
    fetcher = MagicMock(spec=WebContentFetcher)
    if isinstance(fetched, Exception):
        fetcher.fetch_external = AsyncMock(side_effect=fetched)
    else:
        fetcher.fetch_external = AsyncMock(return_value=fetched)

    dial_file_service = MagicMock(spec=DialFileService)
    dial_file_service.write_bytes = AsyncMock(side_effect=write_bytes_side_effect)

    # Real resolution semantics (home under files/appbucket/agent/), no network.
    home_resolver = MagicMock(spec=HomePathResolver)
    home_resolver.resolve_appdata_url = AsyncMock(side_effect=lambda p: f"{_HOME}{p}")
    home_resolver.to_display_path = AsyncMock(side_effect=lambda u: u.removeprefix(_HOME))

    tool = _WebFetchTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=WEB_FETCH_TOOL_CONFIG,
        perf_timer=MagicMock(),
        web_content_fetcher=fetcher,
        dial_file_service=dial_file_service,
        home_resolver=home_resolver,
        max_inline_size=max_inline_size,
    )
    return tool, dial_file_service


class TestLoadIntoContext:
    @pytest.mark.asyncio
    async def test_textual_within_guard_returns_inline_content(self):
        fetched = FetchedBytes(
            data=b"# Title\nbody", content_type="text/markdown", filename="README.md"
        )
        tool, service = _make_tool(fetched)
        result = await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/README.md")
        assert result.content == "# Title\nbody"
        assert result.content_type == "text/markdown"
        assert not result.attachments
        service.write_bytes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_charset_respected(self):
        fetched = FetchedBytes(
            data="café".encode("latin-1"),
            content_type="text/plain; charset=latin-1",
            filename="a.txt",
        )
        tool, _ = _make_tool(fetched)
        result = await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/a.txt")
        assert result.content == "café"

    @pytest.mark.asyncio
    async def test_binary_rejected_pointing_at_save_path(self):
        fetched = FetchedBytes(data=b"\x89PNG\r\n", content_type="image/png", filename="a.png")
        tool, _ = _make_tool(fetched)
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/a.png")
        assert exc.value.parameter_name == "url"
        assert "save_path" in exc.value.message

    @pytest.mark.asyncio
    async def test_missing_content_type_treated_as_binary(self):
        fetched = FetchedBytes(data=b"plain", content_type=None, filename="a")
        tool, _ = _make_tool(fetched)
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/a")
        assert "save_path" in exc.value.message

    @pytest.mark.asyncio
    async def test_oversized_text_rejected_pointing_at_save_path(self):
        big = "a" * 100
        fetched = FetchedBytes(
            data=big.encode("utf-8"), content_type="text/plain", filename="big.txt"
        )
        tool, _ = _make_tool(fetched, max_inline_size=50)
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/big.txt")
        assert exc.value.parameter_name == "url"
        assert "save_path" in exc.value.message

    @pytest.mark.asyncio
    async def test_content_at_cap_rejected(self):
        # Exactly the cap must be rejected so the returned content stays below the
        # offload trigger (which fires at >= threshold).
        data = b"a" * 50
        fetched = FetchedBytes(data=data, content_type="text/plain", filename="x.txt")
        tool, _ = _make_tool(fetched, max_inline_size=50)
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/x.txt")

    @pytest.mark.asyncio
    async def test_fetch_error_propagates(self):
        tool, _ = _make_tool(InvalidToolCallParameterException("url", "egress disabled"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/x")
        assert "egress disabled" in exc.value.message


class TestSaveToWorkspace:
    @pytest.mark.asyncio
    async def test_textual_saved_returns_path_and_preview(self):
        fetched = FetchedBytes(
            data=b"def main():\n    pass\n", content_type="text/x-python", filename="data.py"
        )
        tool, service = _make_tool(fetched)
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="https://x.com/data.py", save_path="analysis/data.py"
        )
        service.write_bytes.assert_awaited_once()
        kwargs = service.write_bytes.await_args.kwargs
        assert kwargs["url"] == f"{_HOME}analysis/data.py"
        assert kwargs["overwrite"] is False
        assert "analysis/data.py" in result.content
        assert "Preview:" in result.content
        assert "def main" in result.content
        assert not result.attachments

    @pytest.mark.asyncio
    async def test_binary_saved_no_inline_body(self):
        fetched = FetchedBytes(data=b"\x89PNG\r\n", content_type="image/png", filename="a.png")
        tool, service = _make_tool(fetched)
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="https://x.com/a.png", save_path="img/a.png"
        )
        assert "img/a.png" in result.content
        assert "image/png" in result.content
        assert "Preview:" not in result.content
        service.write_bytes.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_files_prefixed_save_path_rejected(self):
        fetched = FetchedBytes(data=b"x", content_type="text/plain", filename="x.txt")
        tool, service = _make_tool(fetched)
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, url="https://x.com/x.txt", save_path="files/other/x.txt"
            )
        assert exc.value.parameter_name == "save_path"
        service.write_bytes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_collision_uniquifies_filename(self):
        fetched = FetchedBytes(data=b"x", content_type="text/plain", filename="data.py")
        # First write collides (etag), second succeeds.
        tool, service = _make_tool(
            fetched, write_bytes_side_effect=[EtagMismatchError("conflict"), None]
        )
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="https://x.com/data.py", save_path="data.py"
        )
        assert service.write_bytes.await_count == 2
        # Second (successful) write targeted the uniquified name.
        assert service.write_bytes.await_args.kwargs["url"] == f"{_HOME}data-1.py"
        assert "data-1.py" in result.content

    @pytest.mark.asyncio
    async def test_permission_denied_raises_parameter_error(self):
        fetched = FetchedBytes(data=b"x", content_type="text/plain", filename="x.txt")
        tool, _ = _make_tool(
            fetched, write_bytes_side_effect=DialException("forbidden", status_code=403)
        )
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, url="https://x.com/x.txt", save_path="x.txt"
            )
        assert exc.value.parameter_name == "save_path"
        assert "access denied" in exc.value.message
