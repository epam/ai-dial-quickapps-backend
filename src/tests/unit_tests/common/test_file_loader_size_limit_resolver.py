from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from quickapp.common.file_loader_settings import FileLoaderSettings
from quickapp.common.file_loader_size_limit_resolver import FileLoaderSizeLimitResolver
from quickapp.config.application import Features, FileLoaderConfig


def _resolver(env: int, app: int | None) -> FileLoaderSizeLimitResolver:
    settings = MagicMock(spec=FileLoaderSettings)
    settings.size_limit = env
    app_config = MagicMock()
    app_config.features = Features(file_loader=FileLoaderConfig(size_limit=app))
    return FileLoaderSizeLimitResolver(settings, app_config)


def test_env_default_used_when_app_unset():
    assert _resolver(env=10 * 1024 * 1024, app=None).resolve() == 10 * 1024 * 1024


def test_app_override_wins():
    assert _resolver(env=10 * 1024 * 1024, app=2048).resolve() == 2048


def test_features_none_falls_back_to_env():
    settings = MagicMock(spec=FileLoaderSettings)
    settings.size_limit = 4096
    app_config = MagicMock()
    app_config.features = None
    assert FileLoaderSizeLimitResolver(settings, app_config).resolve() == 4096


def test_settings_real_default_is_10_mib(monkeypatch):
    monkeypatch.delenv("DEFAULT_FILE_LOADER_SIZE_LIMIT", raising=False)
    assert FileLoaderSettings().size_limit == 10 * 1024 * 1024


def test_settings_reads_env_alias(monkeypatch):
    monkeypatch.setenv("DEFAULT_FILE_LOADER_SIZE_LIMIT", "1024")
    assert FileLoaderSettings().size_limit == 1024


def test_file_loader_default_factory_materialises():
    config = FileLoaderConfig()
    assert config.size_limit is None


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_invalid_size_limit_rejected(bad):
    with pytest.raises(ValidationError):
        FileLoaderConfig(size_limit=bad)
