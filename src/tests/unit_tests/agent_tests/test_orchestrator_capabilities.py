from types import SimpleNamespace

import pytest
from aidial_client.types.deployment import Features

from quickapp.core.agent import OrchestratorCapabilities


def _deployment(
    deployment_id: str = "gpt-4",
    input_attachment_types: list[str] | None = None,
    features: SimpleNamespace | Features | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=deployment_id,
        input_attachment_types=input_attachment_types,
        features=features,
    )


def test_deployment_id_and_input_attachment_types_exposed():
    caps = OrchestratorCapabilities(
        deployment=_deployment(  # type: ignore[arg-type]
            deployment_id="gpt-4",
            input_attachment_types=["application/pdf", "image/*"],
        )
    )

    assert caps.deployment_id == "gpt-4"
    assert caps.input_attachment_types == ["application/pdf", "image/*"]


def test_features_exposes_the_deployment_features():
    features = Features(temperature=False, reasoning_efforts=["low"])
    caps = OrchestratorCapabilities(
        deployment=_deployment(features=features)  # type: ignore[arg-type]
    )

    assert caps.features is features


def test_features_empty_when_deployment_has_no_features():
    caps = OrchestratorCapabilities(deployment=_deployment(features=None))  # type: ignore[arg-type]

    assert caps.features == Features()


def test_supports_cache_breakpoints_when_deployment_advertises_cache():
    caps = OrchestratorCapabilities(
        deployment=_deployment(features=SimpleNamespace(cache=True))  # type: ignore[arg-type]
    )

    assert caps.supports_cache_breakpoints is True


@pytest.mark.parametrize(
    "features",
    [SimpleNamespace(cache=None), SimpleNamespace(cache=False), None],
    ids=["cache_none", "cache_false", "no_features"],
)
def test_no_cache_breakpoints_when_cache_not_advertised(features: SimpleNamespace | None):
    caps = OrchestratorCapabilities(deployment=_deployment(features=features))  # type: ignore[arg-type]

    assert caps.supports_cache_breakpoints is False
