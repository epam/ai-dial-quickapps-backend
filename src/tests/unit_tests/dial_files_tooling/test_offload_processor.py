from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client import DialException
from aidial_sdk.chat_completion import Attachment

from quickapp.common.abstract.tool_call_result_processor import ProcessingContext
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._offload_config import ResolvedOffloadConfig
from quickapp.dial_files_tooling._offload_processor import ToolCallResultOffloadProcessor


def _make_config(**overrides) -> ResolvedOffloadConfig:
    defaults = dict(enabled=True, size_threshold=100, excluded_tools=frozenset({"excluded_tool"}))
    defaults.update(overrides)
    return ResolvedOffloadConfig(**defaults)


def _make_attachment_service(upload_url: str = "https://storage/offloaded.txt") -> MagicMock:
    svc = MagicMock()
    svc.upload_bytes = AsyncMock(return_value=MagicMock(url=upload_url))
    return svc


def _make_processor(
    config: ResolvedOffloadConfig | None = None,
    upload_url: str = "https://storage/offloaded.txt",
) -> ToolCallResultOffloadProcessor:
    return ToolCallResultOffloadProcessor(
        config=config or _make_config(),
        attachment_service=_make_attachment_service(upload_url),
    )


def _make_ctx(tool_name: str = "my_tool", tool_call_id: str = "id1") -> ProcessingContext:
    return ProcessingContext(tool_call_id=tool_call_id, tool_name=tool_name)


class TestToolCallResultOffloadProcessor:
    @pytest.mark.asyncio
    async def test_small_content_returned_unchanged(self):
        result = ToolCallResult(content="short", content_type="text/plain")
        proc = _make_processor()
        out = await proc.process(result, _make_ctx())
        assert out.content == "short"

    @pytest.mark.asyncio
    async def test_large_content_is_offloaded(self):
        content = "x" * 200  # threshold=100
        result = ToolCallResult(content=content, content_type="text/plain")
        proc = _make_processor(upload_url="https://storage/offloaded.txt")
        out = await proc.process(result, _make_ctx("fetch_logs"))
        assert "fetch_logs" in out.content
        assert "https://storage/offloaded.txt" in out.content
        assert "internal_file_read_lines" in out.content
        assert "internal_file_search" in out.content

    @pytest.mark.asyncio
    async def test_large_content_attaches_file(self):
        content = "x" * 200
        result = ToolCallResult(content=content, content_type="text/plain")
        proc = _make_processor(upload_url="https://storage/offloaded.txt")
        out = await proc.process(result, _make_ctx())
        assert out.attachments is not None
        assert len(out.attachments) == 1
        assert out.attachments[0].url == "https://storage/offloaded.txt"

    @pytest.mark.asyncio
    async def test_large_content_sets_state_metadata(self):
        content = "x" * 200
        result = ToolCallResult(content=content, content_type="application/json")
        proc = _make_processor()
        out = await proc.process(result, _make_ctx())
        assert out.state is not None
        meta = out.state["offloaded_response"]
        assert meta["file_url"] == "https://storage/offloaded.txt"
        assert meta["original_size"] == len(content.encode("utf-8"))
        assert meta["content_type"] == "application/json"

    @pytest.mark.asyncio
    async def test_excluded_tool_skips_offload(self):
        content = "x" * 200
        result = ToolCallResult(content=content, content_type="text/plain")
        proc = _make_processor()
        out = await proc.process(result, _make_ctx(tool_name="excluded_tool"))
        assert out.content == content

    @pytest.mark.asyncio
    async def test_disabled_skips_offload(self):
        content = "x" * 200
        result = ToolCallResult(content=content, content_type="text/plain")
        proc = _make_processor(config=_make_config(enabled=False))
        out = await proc.process(result, _make_ctx())
        assert out.content == content

    @staticmethod
    def _failing_processor(error: Exception, **config) -> ToolCallResultOffloadProcessor:
        svc = MagicMock()
        svc.upload_bytes = AsyncMock(side_effect=error)
        return ToolCallResultOffloadProcessor(config=_make_config(**config), attachment_service=svc)

    @pytest.mark.asyncio
    async def test_upload_failure_truncates_instead_of_returning_original(self):
        content = "\n".join(f"line {i:04d}" for i in range(1000))
        result = ToolCallResult(content=content, content_type="text/plain")
        proc = self._failing_processor(RuntimeError("storage down"), size_threshold=2000)
        out = await proc.process(result, _make_ctx("fetch_logs"))
        assert len(out.content) <= 2000
        assert out.content.startswith("line 0000\nline 0001")
        assert "'fetch_logs' was too large" in out.content
        assert out.attachments is None
        assert out.state is None

    @pytest.mark.asyncio
    async def test_upload_failure_reports_dial_status_code_as_reason(self):
        proc = self._failing_processor(DialException("secret internal detail", status_code=503))
        out = await proc.process(ToolCallResult(content="x" * 200), _make_ctx())
        assert "could not be saved to DIAL storage (HTTP 503)" in out.content
        assert "secret internal detail" not in out.content

    @pytest.mark.asyncio
    async def test_upload_failure_reports_exception_class_for_other_errors(self):
        proc = self._failing_processor(TimeoutError("https://host/files?token=abc"))
        out = await proc.process(ToolCallResult(content="x" * 200), _make_ctx())
        assert "(TimeoutError)" in out.content
        assert "token=abc" not in out.content

    @pytest.mark.asyncio
    async def test_upload_failure_keeps_other_result_fields(self):
        existing = Attachment(title="a.png", url="files/b/a.png", type="image/png")
        result = ToolCallResult(
            tool_call_id="id1", content="x" * 200, attachments=[existing], state={"k": "v"}
        )
        out = await self._failing_processor(RuntimeError()).process(result, _make_ctx())
        assert out.tool_call_id == "id1"
        assert out.attachments == [existing]
        assert out.state == {"k": "v"}

    @pytest.mark.asyncio
    async def test_high_threshold_skips_offload(self):
        content = "x" * 150
        result = ToolCallResult(content=content, content_type="text/plain")
        proc = _make_processor(config=_make_config(size_threshold=200))
        out = await proc.process(result, _make_ctx())
        assert out.content == content

    @pytest.mark.asyncio
    async def test_existing_attachments_preserved(self):
        content = "x" * 200
        existing = Attachment(
            title="existing.png", url="https://example.com/img.png", type="image/png"
        )
        result = ToolCallResult(content=content, content_type="text/plain", attachments=[existing])
        proc = _make_processor()
        out = await proc.process(result, _make_ctx())
        assert out.attachments is not None
        assert len(out.attachments) == 2
        assert any(a.title == "existing.png" for a in out.attachments)

    @pytest.mark.asyncio
    async def test_upload_receives_raw_utf8_content(self):
        content = "hello world " * 20  # > 100 bytes
        result = ToolCallResult(content=content, content_type="text/plain")
        svc = _make_attachment_service()
        proc = ToolCallResultOffloadProcessor(config=_make_config(), attachment_service=svc)
        await proc.process(result, _make_ctx())
        kwargs = svc.upload_bytes.call_args.kwargs
        assert kwargs["data"] == content.encode("utf-8")
        assert kwargs["content_type"] == "text/plain"
