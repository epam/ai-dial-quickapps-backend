import logging

from quickapp.config.application import Features, StageDisplayConfig, StageDisplayLevel
from quickapp.config.timestamp import ToolCallTimestampConfig
from quickapp.config.tools.display.tool import ToolStageConfig


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


class TestStageDisplayConfig:
    def test_default_level_is_info(self):
        cfg = StageDisplayConfig()
        assert cfg.level == StageDisplayLevel.INFO

    def test_explicit_errors_level(self):
        cfg = StageDisplayConfig(level=StageDisplayLevel.ERRORS)
        assert cfg.level == StageDisplayLevel.ERRORS

    def test_explicit_debug_level(self):
        cfg = StageDisplayConfig(level=StageDisplayLevel.DEBUG)
        assert cfg.level == StageDisplayLevel.DEBUG


class TestFeaturesStageDisplay:
    def test_default_stage_display_level_is_info(self):
        features = Features()
        assert features.stage_display.level == StageDisplayLevel.INFO

    def test_stage_display_from_manifest_errors(self):
        features = Features.model_validate({"stage_display": {"level": "errors"}})
        assert features.stage_display.level == StageDisplayLevel.ERRORS

    def test_stage_display_from_manifest_debug(self):
        features = Features.model_validate({"stage_display": {"level": "debug"}})
        assert features.stage_display.level == StageDisplayLevel.DEBUG


class TestToolStageDeprecationWarning:
    def test_show_false_logs_deprecation_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="quickapp.config.tools.display.tool"):
            ToolStageConfig(show=False)
        assert any("deprecated" in record.message.lower() for record in caplog.records)

    def test_show_true_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="quickapp.config.tools.display.tool"):
            ToolStageConfig(show=True)
        assert not any("deprecated" in record.message.lower() for record in caplog.records)

    def test_show_default_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="quickapp.config.tools.display.tool"):
            ToolStageConfig()
        assert not any("deprecated" in record.message.lower() for record in caplog.records)
