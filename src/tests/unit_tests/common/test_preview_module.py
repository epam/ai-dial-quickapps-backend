from unittest.mock import patch

from injector import Module

from quickapp.app_factory import AppFactory
from quickapp.common.preview import is_preview_module, preview_module


class TestPreviewModuleDecorator:
    def test_decorator_sets_attribute(self):
        @preview_module
        class MyModule(Module):
            pass

        assert getattr(MyModule, "_is_preview_module", False) is True

    def test_is_preview_module_true(self):
        @preview_module
        class MyModule(Module):
            pass

        assert is_preview_module(MyModule()) is True

    def test_is_preview_module_false(self):
        class RegularModule(Module):
            pass

        assert is_preview_module(RegularModule()) is False

    def test_decorator_preserves_class(self):
        @preview_module
        class MyModule(Module):
            pass

        assert MyModule.__name__ == "MyModule"
        assert issubclass(MyModule, Module)

    def test_filtering_logic(self):
        """Verify the filtering pattern used in AppFactory."""

        @preview_module
        class PreviewMod(Module):
            pass

        class StableMod(Module):
            pass

        modules = [StableMod(), PreviewMod(), StableMod()]
        filtered = [m for m in modules if not is_preview_module(m)]
        assert len(filtered) == 2
        assert all(isinstance(m, StableMod) for m in filtered)


class TestGraduatedModulesRegistered:
    """Modules promoted out of preview must be wired with preview features off."""

    def test_registered_when_preview_features_are_off(self):
        with patch.dict("os.environ", {"ENABLE_PREVIEW_FEATURES": "false"}):
            names = {type(m).__name__ for m in AppFactory.build_di_modules()}

        assert {
            "ToolDiscoveryModule",
            "WebToolingModule",
            "RepresentationToolingModule",
            "AgentHooksModule",
            "DialSkillsModule",
            "SkillInvocationModule",
        } <= names
