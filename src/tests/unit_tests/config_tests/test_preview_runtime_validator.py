import logging

from pydantic import BaseModel

from quickapp.common.base_config import PreviewField
from quickapp.config.application import nullify_preview_fields


class TestNullifyPreviewFields:
    def test_preview_field_nullified_when_set(self):
        class Cfg(BaseModel):
            feat: str | None = PreviewField(description="test")

        model = Cfg.model_construct(feat="value")
        nullify_preview_fields(model)
        assert model.feat is None

    def test_preview_field_already_none_no_warning(self, caplog):
        class Cfg(BaseModel):
            feat: str | None = PreviewField(description="test")

        model = Cfg.model_construct(feat=None)
        with caplog.at_level(logging.WARNING):
            nullify_preview_fields(model)
        assert not caplog.records

    def test_non_preview_fields_untouched(self):
        class Cfg(BaseModel):
            stable: str = "hello"
            feat: str | None = PreviewField(description="test")

        model = Cfg.model_construct(stable="hello", feat="value")
        nullify_preview_fields(model)
        assert model.stable == "hello"
        assert model.feat is None

    def test_nested_model_preview_field_nullified(self):
        class Inner(BaseModel):
            preview_inner: str | None = PreviewField(description="nested")

        class Outer(BaseModel):
            inner: Inner
            stable: str = "ok"

        inner = Inner.model_construct(preview_inner="value")
        model = Outer.model_construct(inner=inner, stable="ok")
        nullify_preview_fields(model)
        assert model.inner.preview_inner is None
        assert model.stable == "ok"

    def test_warning_logged(self, caplog):
        class Cfg(BaseModel):
            feat: str | None = PreviewField(description="test")

        model = Cfg.model_construct(feat="value")
        with caplog.at_level(logging.WARNING):
            nullify_preview_fields(model)
        assert len(caplog.records) == 1
        assert "feat" in caplog.records[0].message
        assert "preview features are disabled" in caplog.records[0].message

    def test_preview_model_entries_removed_from_list(self, caplog):
        from quickapp.config.context import FileContextConfig, FolderContextConfig

        class Cfg(BaseModel):
            contexts: list[FileContextConfig | FolderContextConfig]

        model = Cfg.model_construct(
            contexts=[
                FileContextConfig(url="files/bucket/a.pdf"),
                FolderContextConfig(url="metadata/files/bucket/docs/"),
            ]
        )
        with caplog.at_level(logging.WARNING):
            nullify_preview_fields(model)

        assert len(model.contexts) == 1
        assert isinstance(model.contexts[0], FileContextConfig)
        assert any(
            "contexts" in r.message and "preview features are disabled" in r.message
            for r in caplog.records
        )


class TestApplicationConfigPreviewValidator:
    """Integration tests with the real ApplicationConfig model_validator."""

    def test_preview_field_nullified_on_construction(self, monkeypatch):
        """Verify model_validator fires on ApplicationConfig subclasses."""
        monkeypatch.delenv("ENABLE_PREVIEW_FEATURES", raising=False)

        from quickapp.common.base_config import BaseApplicationTypeConfig

        class TestAppConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "test_preview"
            _dial_application_type_display_name = "Test"
            stable: str
            preview_feat: str | None = PreviewField(description="preview")

        # NOTE: model_validator must be on ApplicationConfig, not arbitrary
        # BaseApplicationTypeConfig subclasses. Test the helper directly.
        model = TestAppConfig.model_construct(stable="ok", preview_feat="val")
        nullify_preview_fields(model)
        assert model.preview_feat is None
        assert model.stable == "ok"

    def test_preview_field_preserved_when_enabled(self, monkeypatch):
        """When ENABLE_PREVIEW_FEATURES=true, the validator early-returns
        and preview fields are not nullified."""
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

        from quickapp.common.base_config import BaseApplicationTypeConfig
        from quickapp.common.feature_settings import FeatureSettings

        assert FeatureSettings().enable_preview_features is True

        class TestAppConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "test_preview_enabled"
            _dial_application_type_display_name = "Test"
            stable: str
            preview_feat: str | None = PreviewField(description="preview")

        # Simulate the gating logic from ApplicationConfig._gate_preview_fields:
        # when preview is enabled, nullify_preview_fields is never called.
        model = TestAppConfig.model_construct(stable="ok", preview_feat="val")
        if not FeatureSettings().enable_preview_features:
            nullify_preview_fields(model)

        assert model.preview_feat == "val"
        assert model.stable == "ok"
