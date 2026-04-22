import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment

from quickapp.common.abstract.tool_call_result_processor import ProcessingContext
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.tool_call_result_offload._large_response_processor import LargeResponseProcessor
from quickapp.tool_call_result_offload._settings import ToolCallResultOffloadSettings


def _make_settings(**overrides) -> ToolCallResultOffloadSettings:
    defaults = dict(enabled=True, size_threshold=100, excluded_tools={"excluded_tool"})
    defaults.update(overrides)
    return ToolCallResultOffloadSettings.model_construct(**defaults)


def _make_attachment_service(upload_url: str = "https://storage/offloaded.txt") -> MagicMock:
    uploaded = Attachment(title="offloaded.txt", url=upload_url, type="text/plain")
    svc = MagicMock()
    svc.upload_attachment_to_core = AsyncMock(return_value=uploaded)
    return svc


def _make_app_config(
    size_threshold_override: int | None = None,
    enabled_override: bool | None = None,
) -> MagicMock:
    cfg = MagicMock()
    if size_threshold_override is not None or enabled_override is not None:
        override = MagicMock()
        override.size_threshold = (
            size_threshold_override if size_threshold_override is not None else 40_000
        )
        override.enabled = enabled_override if enabled_override is not None else True
        cfg.tool_defaults.tool_call_result_offload = override
    else:
        cfg.tool_defaults.tool_call_result_offload = None
    return cfg


def _make_processor(
    settings: ToolCallResultOffloadSettings | None = None,
    upload_url: str = "https://storage/offloaded.txt",
    app_config=None,
) -> LargeResponseProcessor:
    return LargeResponseProcessor(
        settings=settings or _make_settings(),
        attachment_service=_make_attachment_service(upload_url),
        app_config=app_config or _make_app_config(),
    )


def _make_ctx(tool_name: str = "my_tool", tool_call_id: str = "id1") -> ProcessingContext:
    return ProcessingContext(tool_call_id=tool_call_id, tool_name=tool_name)


class TestLargeResponseProcessor:
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
        assert "read_file_lines" in out.content
        assert "search_in_file" in out.content

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
    async def test_disabled_processor_skips_offload(self):
        content = "x" * 200
        result = ToolCallResult(content=content, content_type="text/plain")
        proc = _make_processor(settings=_make_settings(enabled=False))
        out = await proc.process(result, _make_ctx())
        assert out.content == content

    @pytest.mark.asyncio
    async def test_per_app_enabled_false_skips_offload(self):
        content = "x" * 200
        result = ToolCallResult(content=content, content_type="text/plain")
        proc = _make_processor(app_config=_make_app_config(enabled_override=False))
        out = await proc.process(result, _make_ctx())
        assert out.content == content

    @pytest.mark.asyncio
    async def test_upload_failure_returns_original(self):
        content = "x" * 200
        result = ToolCallResult(content=content, content_type="text/plain")
        svc = MagicMock()
        svc.upload_attachment_to_core = AsyncMock(side_effect=RuntimeError("storage down"))
        proc = LargeResponseProcessor(
            settings=_make_settings(),
            attachment_service=svc,
            app_config=_make_app_config(),
        )
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
        proc = LargeResponseProcessor(
            settings=_make_settings(),
            attachment_service=svc,
            app_config=_make_app_config(),
        )
        out = await proc.process(result, _make_ctx())
        assert out.content == content

    @pytest.mark.asyncio
    async def test_per_app_threshold_override(self):
        # global threshold=100 would offload, but override=200 means 150-byte content passes through
        content = "x" * 150
        result = ToolCallResult(content=content, content_type="text/plain")
        proc = _make_processor(app_config=_make_app_config(size_threshold_override=200))
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
        proc = LargeResponseProcessor(
            settings=_make_settings(),
            attachment_service=svc,
            app_config=_make_app_config(),
        )
        await proc.process(result, _make_ctx())
        uploaded_att: Attachment = svc.upload_attachment_to_core.call_args[0][0]
        assert uploaded_att.data is not None
        assert base64.b64decode(uploaded_att.data) == content.encode("utf-8")
