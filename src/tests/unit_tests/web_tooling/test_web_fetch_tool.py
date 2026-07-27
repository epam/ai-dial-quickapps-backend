from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import DialException, EtagMismatchError

from quickapp.common import ToolCallResult
from quickapp.common.exceptions import InvalidToolCallParameterException, ToolErrorException
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.shared.external_fetch.external_url_fetcher import (
    ExternalFetchDisabledError,
    FetchedBytes,
)
from quickapp.shared.external_fetch.web_content_fetcher import (
    WebContentFetcher,
    WebContentFetchError,
)
from quickapp.shared.home_path.home_path_resolver import HomePathResolver
from quickapp.web_tooling._tool_configs import WEB_FETCH_TOOL_CONFIG
from quickapp.web_tooling._truncation import compose_truncated_content, split_truncation_notice
from quickapp.web_tooling._web_fetch_stage_wrapper import _WebFetchStageWrapper
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
    async def test_utf8_content_returned_inline(self):
        fetched = FetchedBytes(
            data="café".encode("utf-8"), content_type="text/plain", filename="a.txt"
        )
        tool, _ = _make_tool(fetched)
        result = await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/a.txt")
        assert result.content == "café"

    @pytest.mark.asyncio
    async def test_non_utf8_text_rejected_as_binary(self):
        # Text detection is a UTF-8 decode attempt; non-UTF-8 (e.g. latin-1) fails
        # closed and is treated as a binary body.
        fetched = FetchedBytes(
            data="café".encode("latin-1"), content_type="text/plain", filename="a.txt"
        )
        tool, _ = _make_tool(fetched)
        with pytest.raises(ToolErrorException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/a.txt")
        assert "save_path" in exc.value.error_message

    @pytest.mark.asyncio
    async def test_binary_rejected_pointing_at_save_path(self):
        fetched = FetchedBytes(data=b"\x89PNG\r\n", content_type="image/png", filename="a.png")
        tool, _ = _make_tool(fetched)
        with pytest.raises(ToolErrorException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/a.png")
        assert "save_path" in exc.value.error_message

    @pytest.mark.asyncio
    async def test_missing_content_type_but_decodable_returned_inline(self):
        fetched = FetchedBytes(data=b"plain", content_type=None, filename="a")
        tool, _ = _make_tool(fetched)
        result = await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/a")
        assert result.content == "plain"
        assert result.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_oversized_text_truncated_with_leading_notice(self):
        text = "\n".join(f"line-{i:03d}" for i in range(200))
        total = len(text.encode("utf-8"))
        fetched = FetchedBytes(
            data=text.encode("utf-8"), content_type="text/plain", filename="big.txt"
        )
        tool, service = _make_tool(fetched, max_inline_size=500)
        result = await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/big.txt")
        # The notice leads so it stays visible however large the head is.
        notice, head = split_truncation_notice(result.content)
        assert notice is not None
        assert result.content.startswith(notice)
        assert text.startswith(head)
        assert f"is {total} bytes" in notice
        assert "save_path" in notice
        # Guidance must stay tool-neutral: no other tool availability is assumed.
        assert "internal_file" not in result.content
        service.write_bytes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_truncated_result_stays_below_cap(self):
        # The whole result (notice + head) must stay strictly below the cap so it
        # never reaches the offload trigger (which fires at >= threshold).
        text = "\n".join(f"line-{i:03d}" for i in range(200))
        fetched = FetchedBytes(
            data=text.encode("utf-8"), content_type="text/plain", filename="big.txt"
        )
        tool, _ = _make_tool(fetched, max_inline_size=500)
        result = await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/big.txt")
        assert len(result.content.encode("utf-8")) < 500
        notice, head = split_truncation_notice(result.content)
        assert notice is not None
        assert head  # a realistic cap leaves room for content, not just the notice

    @pytest.mark.asyncio
    async def test_content_at_cap_truncated(self):
        # Exactly the cap must truncate too, so a returned result is always
        # strictly below the cap (and thus below the offload trigger).
        data = b"a" * 500
        fetched = FetchedBytes(data=data, content_type="text/plain", filename="x.txt")
        tool, _ = _make_tool(fetched, max_inline_size=500)
        result = await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com/x.txt")
        assert result.content.startswith("[Truncated: ")
        assert len(result.content.encode("utf-8")) < 500

    @pytest.mark.asyncio
    async def test_scheme_error_mapped_to_parameter_error(self):
        # A wrong-kind-of-URL domain error becomes a retryable parameter error.
        tool, _ = _make_tool(WebContentFetchError("URL files/x is already in DIAL storage."))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, url="files/x")
        assert exc.value.parameter_name == "url"
        assert "DIAL storage" in exc.value.message

    @pytest.mark.asyncio
    async def test_egress_failure_mapped_to_tool_error(self):
        # The URL is valid; an egress failure is a tool error, not a bad parameter.
        tool, _ = _make_tool(ExternalFetchDisabledError(reason="admin", url="https://x.com"))
        with pytest.raises(ToolErrorException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, url="https://x.com")
        assert "EXTERNAL_URL_FETCH_ENABLED" in exc.value.error_message


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


class TestSplitTruncationNotice:
    def test_composed_content_round_trips(self):
        notice = "[Truncated: fetched content is 9 bytes (text/plain). x]"
        content = compose_truncated_content(notice, "abc")
        assert split_truncation_notice(content) == (notice, "abc")

    def test_non_truncated_content_returned_unchanged(self):
        assert split_truncation_notice("# README\nbody") == (None, "# README\nbody")

    def test_fetched_text_resembling_a_notice_needs_the_separator(self):
        # A page whose text merely starts like a notice but was not composed by
        # the tool (no blank-line separator) is left intact.
        content = "[Truncated: some page text without a separator"
        assert split_truncation_notice(content) == (None, content)


class TestStageRendering:
    def _render(self, content: str) -> str:
        wrapper = _WebFetchStageWrapper(stage=MagicMock())
        result = ToolCallResult(content=content, content_type="text/plain")
        return wrapper._build_debug_info_from_result(result)

    def test_truncation_notice_rendered_outside_verbatim_block(self):
        notice = "[Truncated: fetched content is 9 bytes (text/plain). x]"
        info = self._render(compose_truncated_content(notice, "abc"))
        assert info.startswith(f"**{notice}**")
        # Only the fetched head lands inside the verbatim content block.
        _, content_block = info.split("**Content:**")
        assert "abc" in content_block
        assert "[Truncated" not in content_block

    def test_regular_content_rendered_without_notice(self):
        info = self._render("# README\nbody")
        assert info.startswith("**Content:**")
        assert "[Truncated" not in info
