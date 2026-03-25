from unittest.mock import MagicMock

from chat_stream_shared.dial_parse import parse_dial_chat_completion_chunk


def test_dial_chunk_usage_and_statistics():
    chunk = MagicMock()
    chunk.choices = []
    chunk.usage = MagicMock()
    chunk.model_extra = {"statistics": {"usage_per_model": [{"model": "m", "prompt_tokens": 1}]}}

    fp, deltas = parse_dial_chat_completion_chunk(chunk)
    assert fp.raw_usage is chunk.usage
    assert fp.statistics == [{"model": "m", "prompt_tokens": 1}]
    assert deltas == []


def test_dial_delta_attachments_branch():
    att = MagicMock()
    cc = MagicMock()
    cc.attachments = [att]
    cc.state = None
    delta = MagicMock()
    delta.content = "hi"
    delta.custom_content = cc
    ch = MagicMock()
    ch.delta = delta
    chunk = MagicMock()
    chunk.choices = [ch]
    chunk.usage = None
    chunk.model_extra = {}

    fp, deltas = parse_dial_chat_completion_chunk(chunk)
    assert len(deltas) == 1
    assert deltas[0].content == "hi"
    assert deltas[0].custom is not None
    assert deltas[0].custom.sdk_attachments == [att]
    assert deltas[0].custom.state is None


def test_dial_delta_state_branch():
    cc = MagicMock()
    cc.attachments = None
    cc.state = {"x": 1}
    delta = MagicMock()
    delta.content = None
    delta.custom_content = cc
    ch = MagicMock()
    ch.delta = delta
    chunk = MagicMock()
    chunk.choices = [ch]
    chunk.usage = None
    chunk.model_extra = {}

    _, deltas = parse_dial_chat_completion_chunk(chunk)
    assert deltas[0].custom is not None
    assert deltas[0].custom.state == {"x": 1}
    assert deltas[0].custom.sdk_attachments == []
