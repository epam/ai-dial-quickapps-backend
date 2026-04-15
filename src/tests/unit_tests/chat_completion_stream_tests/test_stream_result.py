"""Tests for ``quickapp.common.chat_completion_stream.stream_result``."""

from unittest.mock import MagicMock

from aidial_sdk.chat_completion import Attachment

from quickapp.common.chat_completion_stream.models import ChunkUsageFootprint
from quickapp.common.chat_completion_stream.stream_result import (
    ChatStreamAccumulator,
    Usage,
    ensure_attachment_url_or_data,
)


def test_apply_usage_footprint_raw_usage_none_uses_token_pair():
    acc = ChatStreamAccumulator()
    acc.apply_usage_footprint(ChunkUsageFootprint(prompt_tokens=10, completion_tokens=20))
    assert acc.usage is not None
    assert acc.usage.prompt_tokens == 10
    assert acc.usage.completion_tokens == 20


def test_apply_usage_footprint_incomplete_tokens_leaves_usage_unchanged():
    acc = ChatStreamAccumulator()
    acc.set_usage(Usage(1, 1))
    acc.apply_usage_footprint(ChunkUsageFootprint(prompt_tokens=5, completion_tokens=None))
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


def test_fix_sdk_attachment_sets_data_when_no_url_no_reference():
    att = MagicMock()
    att.data = None
    att.url = None
    att.reference_url = None
    ensure_attachment_url_or_data(att)
    assert att.data == ""


def test_fix_sdk_attachment_copies_reference_url_to_url():
    att = MagicMock()
    att.data = None
    att.url = None
    att.reference_url = "files/ref"
    ensure_attachment_url_or_data(att)
    assert att.url == "files/ref"
