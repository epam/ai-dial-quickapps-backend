"""Tests for the LOG_PAYLOADS settings (LoggingSettings, issue #436)."""

from quickapp.config.logging_settings import LoggingSettings


class TestPayloadSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("LOG_PAYLOADS", raising=False)
        monkeypatch.delenv("LOG_PAYLOADS_MAX_LENGTH", raising=False)

        settings = LoggingSettings()

        assert settings.log_payloads is False
        assert settings.log_payloads_max_length == 2000

    def test_log_payloads_parsed_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_PAYLOADS", "true")

        assert LoggingSettings().log_payloads is True

    def test_max_length_parsed_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_PAYLOADS_MAX_LENGTH", "50")

        assert LoggingSettings().log_payloads_max_length == 50
