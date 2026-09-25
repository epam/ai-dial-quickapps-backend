from types import SimpleNamespace

from quickapp.core.agent import OrchestratorCapabilities


def _deployment(
    deployment_id: str = "gpt-4",
    input_attachment_types: list[str] | None = None,
    features: SimpleNamespace | None = None,
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


def test_reasoning_efforts_exposes_the_advertised_values():
    caps = OrchestratorCapabilities(
        deployment=_deployment(  # type: ignore[arg-type]
            features=SimpleNamespace(reasoning_efforts=["low", "medium", "high"]),
        )
    )

    assert caps.reasoning_efforts == ["low", "medium", "high"]
    assert caps.supports_reasoning_effort("medium") is True
    assert caps.supports_reasoning_effort("none") is False


def test_reasoning_efforts_empty_when_deployment_advertises_none():
    """An empty list means no value is supported, not that every value is."""
    caps = OrchestratorCapabilities(
        deployment=_deployment(  # type: ignore[arg-type]
            features=SimpleNamespace(reasoning_efforts=[]),
        )
    )

    assert caps.reasoning_efforts == []
    assert caps.supports_reasoning_effort("low") is False


def test_reasoning_efforts_empty_when_deployment_has_no_features():
    caps = OrchestratorCapabilities(deployment=_deployment(features=None))  # type: ignore[arg-type]

    assert caps.reasoning_efforts == []
    assert caps.supports_reasoning_effort("low") is False
