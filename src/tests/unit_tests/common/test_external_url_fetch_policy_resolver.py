from unittest.mock import MagicMock

import pytest

from quickapp.common.external_fetch_settings import ExternalFetchSettings
from quickapp.common.external_url_fetch_policy_resolver import ExternalUrlFetchPolicyResolver
from quickapp.config.application import ExternalUrlFetchConfig, Features, FileLoadingConfig


def _resolver(admin_allow: bool, app_enabled: bool | None) -> ExternalUrlFetchPolicyResolver:
    settings = MagicMock(spec=ExternalFetchSettings)
    settings.allow = admin_allow
    app_config = MagicMock()
    app_config.features = Features(
        file_loading=FileLoadingConfig(),
        external_url_fetch=ExternalUrlFetchConfig(enabled=app_enabled),
    )
    return ExternalUrlFetchPolicyResolver(settings, app_config)


@pytest.mark.parametrize("app_enabled", [None, True, False])
def test_admin_disallow_overrides_any_app(app_enabled: bool | None):
    assert _resolver(admin_allow=False, app_enabled=app_enabled).resolve_reason() == "admin"


def test_admin_allow_app_unset_is_allowed():
    assert _resolver(admin_allow=True, app_enabled=None).resolve_reason() == "allowed"


def test_admin_allow_app_true_is_allowed():
    assert _resolver(admin_allow=True, app_enabled=True).resolve_reason() == "allowed"


def test_admin_allow_app_false_blocks_with_builder_reason():
    assert _resolver(admin_allow=True, app_enabled=False).resolve_reason() == "builder"


def test_features_none_falls_back_to_admin():
    settings = MagicMock(spec=ExternalFetchSettings)
    settings.allow = True
    app_config = MagicMock()
    app_config.features = None
    assert ExternalUrlFetchPolicyResolver(settings, app_config).resolve_reason() == "allowed"


def test_settings_default_is_disabled(monkeypatch):
    monkeypatch.delenv("ALLOW_EXTERNAL_URL_FETCH", raising=False)
    assert ExternalFetchSettings().allow is False


def test_settings_reads_env_alias(monkeypatch):
    monkeypatch.setenv("ALLOW_EXTERNAL_URL_FETCH", "true")
    assert ExternalFetchSettings().allow is True


def test_settings_redirect_cap_default(monkeypatch):
    monkeypatch.delenv("EXTERNAL_URL_FETCH_MAX_REDIRECTS", raising=False)
    assert ExternalFetchSettings().max_redirects == 5


def test_settings_redirect_cap_hard_ceiling_enforced(monkeypatch):
    monkeypatch.setenv("EXTERNAL_URL_FETCH_MAX_REDIRECTS", "11")
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExternalFetchSettings()


def test_settings_connect_timeout_must_be_positive(monkeypatch):
    monkeypatch.setenv("EXTERNAL_URL_FETCH_CONNECT_TIMEOUT_SECONDS", "0")
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExternalFetchSettings()


def test_external_url_fetch_config_default_is_none():
    assert ExternalUrlFetchConfig().enabled is None
