import pytest
from pydantic import ValidationError

from quickapp.agent_hooks._background_hook_settings import BackgroundHookSettings


def test_defaults_warn_below_the_limit() -> None:
    settings = BackgroundHookSettings()

    assert (settings.warn_threshold, settings.max_concurrent) == (40, 50)


@pytest.mark.parametrize("threshold", [50, 51])
def test_threshold_must_be_below_the_limit(threshold: int) -> None:
    with pytest.raises(ValidationError, match="warn_threshold"):
        BackgroundHookSettings(warn_threshold=threshold, max_concurrent=50)


def test_threshold_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKGROUND_HOOKS_WARN_THRESHOLD", "7")

    assert BackgroundHookSettings().warn_threshold == 7
