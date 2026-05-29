from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from quickapp.config.application import Features, FileLoadingConfig
from quickapp.config_resolvers.file_loading_settings import FileLoadingSettings
from quickapp.config_resolvers.file_loading_size_limit_resolver import FileLoadingSizeLimitResolver


def _resolver(env: int, app: int | None) -> FileLoadingSizeLimitResolver:
    settings = MagicMock(spec=FileLoadingSettings)
    settings.size_limit = env
    app_config = MagicMock()
    app_config.features = Features(file_loading=FileLoadingConfig(size_limit=app))
    return FileLoadingSizeLimitResolver(settings, app_config)


def test_env_default_used_when_app_unset():
    assert _resolver(env=10 * 1024 * 1024, app=None).resolve() == 10 * 1024 * 1024


def test_app_override_wins():
    assert _resolver(env=10 * 1024 * 1024, app=2048).resolve() == 2048


def test_features_none_falls_back_to_env():
    settings = MagicMock(spec=FileLoadingSettings)
    settings.size_limit = 4096
    app_config = MagicMock()
    app_config.features = None
    assert FileLoadingSizeLimitResolver(settings, app_config).resolve() == 4096


def test_settings_real_default_is_10_mib(monkeypatch):
    monkeypatch.delenv("DEFAULT_FILE_LOADING_SIZE_LIMIT", raising=False)
    assert FileLoadingSettings().size_limit == 10 * 1024 * 1024


def test_settings_reads_env_alias(monkeypatch):
    monkeypatch.setenv("DEFAULT_FILE_LOADING_SIZE_LIMIT", "1024")
    assert FileLoadingSettings().size_limit == 1024


def test_file_loading_default_factory_materialises():
    config = FileLoadingConfig()
    assert config.size_limit is None


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_invalid_size_limit_rejected(bad):
    with pytest.raises(ValidationError):
        FileLoadingConfig(size_limit=bad)
