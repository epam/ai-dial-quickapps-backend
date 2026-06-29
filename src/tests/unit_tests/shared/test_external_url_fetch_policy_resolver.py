from unittest.mock import MagicMock

import pytest

from quickapp.config.application import ExternalUrlFetchConfig, Features, FileLoadingConfig
from quickapp.shared.external_fetch._external_fetch_settings import ExternalFetchSettings
from quickapp.shared.external_fetch.external_url_fetch_policy_resolver import (
    ExternalUrlFetchPolicyResolver,
)


def _resolver(
    admin_enabled: bool = True,
    app_enabled: bool | None = None,
    admin_host_allowlist: list[str] | None = None,
    app_host_allowlist: list[str] | None = None,
) -> ExternalUrlFetchPolicyResolver:
    settings = MagicMock(spec=ExternalFetchSettings)
    settings.enabled = admin_enabled
    settings.host_allowlist = admin_host_allowlist
    app_config = MagicMock()
    app_config.features = Features(
        file_loading=FileLoadingConfig(),
        external_url_fetch=ExternalUrlFetchConfig(
            enabled=app_enabled,
            host_allowlist=app_host_allowlist,
        ),
    )
    return ExternalUrlFetchPolicyResolver(settings, app_config)


@pytest.mark.parametrize("app_enabled", [None, True, False])
def test_admin_disallow_overrides_any_app(app_enabled: bool | None):
    assert _resolver(admin_enabled=False, app_enabled=app_enabled).resolve_reason() == "admin"


def test_admin_enabled_app_unset_is_allowed():
    assert _resolver(admin_enabled=True, app_enabled=None).resolve_reason() == "allowed"


def test_admin_enabled_app_true_is_allowed():
    assert _resolver(admin_enabled=True, app_enabled=True).resolve_reason() == "allowed"


def test_admin_enabled_app_false_blocks_with_builder_reason():
    assert _resolver(admin_enabled=True, app_enabled=False).resolve_reason() == "builder"


def test_features_none_falls_back_to_admin():
    settings = MagicMock(spec=ExternalFetchSettings)
    settings.enabled = True
    app_config = MagicMock()
    app_config.features = None
    assert ExternalUrlFetchPolicyResolver(settings, app_config).resolve_reason() == "allowed"


def test_settings_default_is_disabled(monkeypatch):
    monkeypatch.delenv("EXTERNAL_URL_FETCH_ENABLED", raising=False)
    assert ExternalFetchSettings().enabled is False


def test_settings_reads_env_alias(monkeypatch):
    monkeypatch.setenv("EXTERNAL_URL_FETCH_ENABLED", "true")
    assert ExternalFetchSettings().enabled is True


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
    assert ExternalUrlFetchConfig().host_allowlist is None


# ---------------------------------------------------------------------------
# resolve_host
# ---------------------------------------------------------------------------


def test_resolve_host_no_lists_is_allowed():
    assert _resolver().resolve_host("example.com") == "allowed"


def test_resolve_host_admin_only_match():
    r = _resolver(admin_host_allowlist=["example.com", "*.cdn.net"])
    assert r.resolve_host("example.com") == "allowed"
    assert r.resolve_host("a.cdn.net") == "allowed"


def test_resolve_host_admin_only_no_match():
    r = _resolver(admin_host_allowlist=["example.com"])
    assert r.resolve_host("evil.com") == "admin_allowlist"


def test_resolve_host_builder_only_match():
    r = _resolver(app_host_allowlist=["example.com"])
    assert r.resolve_host("example.com") == "allowed"


def test_resolve_host_builder_only_no_match():
    r = _resolver(app_host_allowlist=["example.com"])
    assert r.resolve_host("evil.com") == "builder_allowlist"


def test_resolve_host_admin_rejects_first_when_both_set():
    r = _resolver(
        admin_host_allowlist=["example.com"],
        app_host_allowlist=["evil.com"],
    )
    assert r.resolve_host("evil.com") == "admin_allowlist"


def test_resolve_host_intersection_match():
    r = _resolver(
        admin_host_allowlist=["example.com", "partner.io"],
        app_host_allowlist=["example.com"],
    )
    assert r.resolve_host("example.com") == "allowed"
    assert r.resolve_host("partner.io") == "builder_allowlist"


def test_resolve_host_features_none_consults_admin_only():
    settings = MagicMock(spec=ExternalFetchSettings)
    settings.enabled = True
    settings.host_allowlist = ["example.com"]
    app_config = MagicMock()
    app_config.features = None
    r = ExternalUrlFetchPolicyResolver(settings, app_config)
    assert r.resolve_host("example.com") == "allowed"
    assert r.resolve_host("evil.com") == "admin_allowlist"


def test_resolve_host_empty_builder_list_blocks_everything():
    r = _resolver(app_host_allowlist=[])
    assert r.resolve_host("anything.com") == "builder_allowlist"


# ---------------------------------------------------------------------------
# ExternalFetchSettings.host_allowlist parsing
# ---------------------------------------------------------------------------


def test_settings_host_allowlist_default_is_none(monkeypatch):
    monkeypatch.delenv("EXTERNAL_URL_FETCH_HOST_ALLOWLIST", raising=False)
    assert ExternalFetchSettings().host_allowlist is None


def test_settings_host_allowlist_parses_single_value(monkeypatch):
    monkeypatch.setenv("EXTERNAL_URL_FETCH_HOST_ALLOWLIST", "example.com")
    assert ExternalFetchSettings().host_allowlist == ["example.com"]


def test_settings_host_allowlist_parses_csv(monkeypatch):
    monkeypatch.setenv("EXTERNAL_URL_FETCH_HOST_ALLOWLIST", "example.com,*.cdn.net,partner.io")
    assert ExternalFetchSettings().host_allowlist == [
        "example.com",
        "*.cdn.net",
        "partner.io",
    ]


def test_settings_host_allowlist_strips_whitespace(monkeypatch):
    monkeypatch.setenv("EXTERNAL_URL_FETCH_HOST_ALLOWLIST", " example.com , *.cdn.net ")
    assert ExternalFetchSettings().host_allowlist == ["example.com", "*.cdn.net"]


def test_settings_host_allowlist_empty_value_collapses_to_none(monkeypatch):
    monkeypatch.setenv("EXTERNAL_URL_FETCH_HOST_ALLOWLIST", "  ,  ,  ")
    assert ExternalFetchSettings().host_allowlist is None
