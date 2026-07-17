"""Tests for the payload-debugging switch (common.payload_logging, issue #436)."""

import logging
from types import SimpleNamespace

import pytest

from quickapp.common.payload_logging import (
    _truncate,
    configure_payload_logging,
    log_payload,
    payloads_enabled,
    summarize_roles,
)


@pytest.fixture(autouse=True)
def reset_payload_config():
    """The switch is module-global; restore the (off) defaults after each test."""
    yield
    configure_payload_logging(enabled=False, max_length=2000)


class TestConfigureAndEnabled:
    def test_disabled_by_default(self):
        assert payloads_enabled() is False

    def test_configure_toggles_enabled(self):
        configure_payload_logging(enabled=True, max_length=50)
        assert payloads_enabled() is True


class TestTruncate:
    def test_short_value_unchanged(self):
        configure_payload_logging(enabled=True, max_length=10)
        assert _truncate("hello") == "hello"

    def test_value_at_cap_not_truncated(self):
        configure_payload_logging(enabled=True, max_length=5)
        assert _truncate("abcde") == "abcde"

    def test_long_value_truncated_with_marker(self):
        configure_payload_logging(enabled=True, max_length=5)
        result = _truncate("abcdefghij")
        assert result.startswith("abcde")
        assert "abcdefghij" not in result
        assert len(result) > len("abcde")  # a marker was appended

    def test_non_string_is_stringified(self):
        configure_payload_logging(enabled=True, max_length=100)
        assert _truncate({"a": 1}) == "{'a': 1}"


class TestLogPayload:
    def test_noop_when_disabled(self, caplog):
        configure_payload_logging(enabled=False, max_length=2000)
        logger = logging.getLogger("quickapp.test.payload")
        with caplog.at_level(logging.DEBUG, logger="quickapp.test.payload"):
            log_payload(logger, "message body: %s", "secret user content")
        assert caplog.records == []

    def test_emits_and_truncates_when_enabled(self, caplog):
        configure_payload_logging(enabled=True, max_length=4)
        logger = logging.getLogger("quickapp.test.payload")
        with caplog.at_level(logging.DEBUG, logger="quickapp.test.payload"):
            log_payload(logger, "body: %s", "abcdefgh")
        assert len(caplog.records) == 1
        rendered = caplog.records[0].getMessage()
        assert "abcd" in rendered
        assert "abcdefgh" not in rendered


class TestSummarizeRoles:
    def test_counts_object_roles(self):
        messages = [
            SimpleNamespace(role="user"),
            SimpleNamespace(role="assistant"),
            SimpleNamespace(role="user"),
        ]
        counts = summarize_roles(messages)
        assert counts["user"] == 2
        assert counts["assistant"] == 1

    def test_counts_dict_roles(self):
        counts = summarize_roles([{"role": "system"}, {"role": "user"}])
        assert counts["system"] == 1
        assert counts["user"] == 1

    def test_missing_role_falls_under_unknown(self):
        counts = summarize_roles([{"content": "x"}, object()])
        assert counts["unknown"] == 2
