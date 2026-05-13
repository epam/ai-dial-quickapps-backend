from quickapp.config.application import Features
from quickapp.config.timestamp import ToolCallTimestampConfig


class TestFeaturesConfig:
    def test_default_features_has_timestamp_enabled(self):
        features = Features()
        assert features.timestamp is not None
        assert isinstance(features.timestamp, ToolCallTimestampConfig)

    def test_timestamp_none_disables(self):
        features = Features(timestamp=None)
        assert features.timestamp is None

    def test_explicit_timestamp_config(self):
        features = Features(timestamp=ToolCallTimestampConfig())
        assert features.timestamp is not None
        assert features.timestamp.injection_strategy == "tool_call"

    def test_empty_dict_creates_default(self):
        features = Features.model_validate({})
        assert features.timestamp is not None
