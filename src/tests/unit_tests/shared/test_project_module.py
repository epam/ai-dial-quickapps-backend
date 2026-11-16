from quickapp.app_factory import AppFactory
from quickapp.common.preview import is_preview_module
from quickapp.core import core_module
from quickapp.shared import shared_module
from quickapp.shared.project.project_module import ProjectModule


def test_project_module_is_preview_gated():
    assert is_preview_module(ProjectModule())


def test_project_module_is_dropped_with_preview_off(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "false")

    assert not any(isinstance(m, ProjectModule) for m in AppFactory.build_di_modules())


def test_prompt_section_directly_follows_the_app_prompt(monkeypatch):
    """Prompt parts keep module registration order; the app's own prompt comes from
    ``core_module``, so ``ProjectModule`` must be the very next module."""
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    modules = AppFactory.build_di_modules()

    assert isinstance(modules[len(core_module)], ProjectModule)
    assert isinstance(shared_module[0], ProjectModule)
