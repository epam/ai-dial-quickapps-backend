import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment

from quickapp.common.abstract.tool_call_result_processor import ProcessingContext
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.shared.dial_files._offload_config import ResolvedOffloadConfig
from quickapp.shared.dial_files._offload_processor import ToolCallResultOffloadProcessor


def _make_config(**overrides) -> ResolvedOffloadConfig:
    defaults = dict(enabled=True, size_threshold=100, excluded_tools=frozenset({"excluded_tool"}))
    defaults.update(overrides)
    return ResolvedOffloadConfig(**defaults)


def _make_attachment_service(upload_url: str = "https://storage/offloaded.txt") -> MagicMock:
    uploaded = Attachment(title="offloaded.txt", url=upload_url, type="text/plain")
    svc = MagicMock()
    svc.upload_attachment_to_core = AsyncMock(return_value=uploaded)
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

    @pytest.mark.asyncio
    async def test_upload_failure_returns_original(self):
        content = "x" * 200
        result = ToolCallResult(content=content, content_type="text/plain")
        svc = MagicMock()
        svc.upload_attachment_to_core = AsyncMock(side_effect=RuntimeError("storage down"))
        proc = ToolCallResultOffloadProcessor(config=_make_config(), attachment_service=svc)
        out = await proc.process(result, _make_ctx())
        assert out.content == content

    @pytest.mark.asyncio
    async def test_upload_returns_no_url_returns_original(self):
        content = "x" * 200
        result = ToolCallResult(content=content, content_type="text/plain")
        no_url_attachment = MagicMock()
        no_url_attachment.url = None
        svc = MagicMock()
        svc.upload_attachment_to_core = AsyncMock(return_value=no_url_attachment)
        proc = ToolCallResultOffloadProcessor(config=_make_config(), attachment_service=svc)
        out = await proc.process(result, _make_ctx())
        assert out.content == content

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
    async def test_upload_receives_base64_encoded_content(self):
        content = "hello world " * 20  # > 100 bytes
        result = ToolCallResult(content=content, content_type="text/plain")
        svc = _make_attachment_service()
        proc = ToolCallResultOffloadProcessor(config=_make_config(), attachment_service=svc)
        await proc.process(result, _make_ctx())
        uploaded_att: Attachment = svc.upload_attachment_to_core.call_args[0][0]
        assert uploaded_att.data is not None
        assert base64.b64decode(uploaded_att.data) == content.encode("utf-8")
