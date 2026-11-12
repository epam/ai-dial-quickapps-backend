from unittest.mock import MagicMock

from quickapp.config.application import (
    Features,
    InitializationIssueLevel,
    InitializationIssuesConfig,
)
from quickapp.shared.config_resolvers.initialization_issues_level_resolver import (
    InitializationIssuesLevelResolver,
)
from quickapp.shared.config_resolvers.initialization_issues_settings import (
    InitializationIssuesSettings,
)


def _resolver(
    env: InitializationIssueLevel, app: InitializationIssueLevel | None
) -> InitializationIssuesLevelResolver:
    settings = MagicMock(spec=InitializationIssuesSettings)
    settings.level = env
    app_config = MagicMock()
    app_config.features = Features(initialization_issues=InitializationIssuesConfig(level=app))
    return InitializationIssuesLevelResolver(settings, app_config)


def test_app_level_overrides_env():
    resolver = _resolver(env=InitializationIssueLevel.WARNING, app=InitializationIssueLevel.ERROR)
    assert resolver.resolve() == InitializationIssueLevel.ERROR


def test_unset_app_level_defers_to_env():
    resolver = _resolver(env=InitializationIssueLevel.CRITICAL, app=None)
    assert resolver.resolve() == InitializationIssueLevel.CRITICAL


def test_features_none_defers_to_env():
    settings = MagicMock(spec=InitializationIssuesSettings)
    settings.level = InitializationIssueLevel.ERROR
    app_config = MagicMock()
    app_config.features = None
    resolver = InitializationIssuesLevelResolver(settings, app_config)
    assert resolver.resolve() == InitializationIssueLevel.ERROR


def test_env_defaults_to_warning(monkeypatch):
    monkeypatch.delenv("DEFAULT_INITIALIZATION_ISSUES_LEVEL", raising=False)
    assert InitializationIssuesSettings().level == InitializationIssueLevel.WARNING


def test_env_level_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("DEFAULT_INITIALIZATION_ISSUES_LEVEL", "Critical")
    assert InitializationIssuesSettings().level == InitializationIssueLevel.CRITICAL
