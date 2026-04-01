from quickapp.config.application import Features
from quickapp.config.timestamp import ToolCallTimestampConfig


class TestFeaturesConfig:
    def test_default_features_has_timestamp_enabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        features = Features()
        assert features.timestamp is not None
        assert isinstance(features.timestamp, ToolCallTimestampConfig)

    def test_timestamp_none_disables(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        features = Features(timestamp=None)
        assert features.timestamp is None

    def test_explicit_timestamp_config(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        features = Features(timestamp=ToolCallTimestampConfig())
        assert features.timestamp is not None
        assert features.timestamp.injection_strategy == "tool_call"

    def test_empty_dict_creates_default(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        features = Features.model_validate({})
        assert features.timestamp is not None

    def test_preview_gating_nullifies_timestamp(self, monkeypatch):
        monkeypatch.delenv("ENABLE_PREVIEW_FEATURES", raising=False)
        from quickapp.config.application import nullify_preview_fields

        features = Features()
        nullify_preview_fields(features)
        assert features.timestamp is None
