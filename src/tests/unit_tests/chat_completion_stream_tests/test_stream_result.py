"""Tests for ``quickapp.common.chat_completion_stream.stream_result``."""

from unittest.mock import MagicMock

from aidial_sdk.chat_completion import Attachment

from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint
from quickapp.common.chat_completion_stream.stream_result import (
    ChatStreamAccumulator,
    Usage,
    attachment_to_sdk,
    fix_sdk_attachment,
)


def test_apply_usage_footprint_prefers_raw_usage():
    acc = ChatStreamAccumulator()
    raw = object()
    acc.apply_usage_footprint(
        ChunkUsageFootprint(
            prompt_tokens=1,
            completion_tokens=2,
            raw_usage=raw,
        )
    )
    assert acc.usage is raw


def test_apply_usage_footprint_raw_usage_none_uses_token_pair():
    acc = ChatStreamAccumulator()
    acc.apply_usage_footprint(
        ChunkUsageFootprint(prompt_tokens=10, completion_tokens=20, raw_usage=None)
    )
    assert acc.usage is not None
    assert acc.usage.prompt_tokens == 10
    assert acc.usage.completion_tokens == 20


def test_apply_usage_footprint_incomplete_tokens_leaves_usage_unchanged():
    acc = ChatStreamAccumulator()
    acc.set_usage(Usage(1, 1))
    acc.apply_usage_footprint(
        ChunkUsageFootprint(prompt_tokens=5, completion_tokens=None, raw_usage=None)
    )
    assert acc.usage.prompt_tokens == 1
    assert acc.usage.completion_tokens == 1


def test_merge_state_and_property_empty():
    acc = ChatStreamAccumulator()
    assert acc.state is None
    acc.merge_state({})
    assert acc.state is None
    acc.merge_state({"a": 1})
    assert acc.state == {"a": 1}
    acc.merge_state({"b": 2})
    assert acc.state == {"a": 1, "b": 2}


def test_append_stage_delta_accumulates_by_index():
    acc = ChatStreamAccumulator()
    acc.append_stage_delta({"name": "A", "content": "x"}, position=0)
    acc.append_stage_delta({"content": "y"}, position=0)
    stages = acc.stages
    assert len(stages) == 1
    assert stages[0]["name"] == "A"
    assert stages[0]["content"] == "xy"


def test_attachments_or_none():
    acc = ChatStreamAccumulator()
    assert acc.attachments_or_none is None
    att = Attachment(type="text/plain", title="t", data="aGk=")
    acc.append_attachment(att)
    assert acc.attachments_or_none == [att]


def test_attachment_to_sdk_delegates_model_dump():
    api_att = MagicMock()
    api_att.model_dump.return_value = {
        "type": "image/png",
        "title": "i",
        "data": None,
        "url": "files/x",
        "reference_url": None,
        "reference_type": None,
    }
    sdk = attachment_to_sdk(api_att)
    assert isinstance(sdk, Attachment)
    assert sdk.url == "files/x"


def test_fix_sdk_attachment_sets_data_when_no_url_no_reference():
    att = MagicMock()
    att.data = None
    att.url = None
    att.reference_url = None
    fix_sdk_attachment(att)
    att.__setitem__.assert_called_once_with("data", "")


def test_fix_sdk_attachment_copies_reference_url_to_url():
    att = MagicMock()
    att.data = None
    att.url = None
    att.reference_url = "files/ref"
    fix_sdk_attachment(att)
    assert att.url == "files/ref"
