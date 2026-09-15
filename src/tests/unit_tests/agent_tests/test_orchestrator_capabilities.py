from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize(
    "mime, expected",
    [
        ("application/pdf", True),
        ("image/png", True),
        ("text/csv", False),
    ],
)
def test_orchestrator_accepts_mime_type_matches_input_attachment_types(mime: str, expected: bool):
    caps = OrchestratorCapabilities(
        deployment=_deployment(  # type: ignore[arg-type]
            input_attachment_types=["application/pdf", "image/*"],
        )
    )

    assert caps.orchestrator_accepts_mime_type(mime) is expected


def test_orchestrator_accepts_mime_type_returns_false_when_input_attachment_types_is_none():
    caps = OrchestratorCapabilities(
        deployment=_deployment(input_attachment_types=None),  # type: ignore[arg-type]
    )

    assert caps.orchestrator_accepts_mime_type("application/pdf") is False
    assert caps.orchestrator_accepts_mime_type("image/png") is False


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


def test_app_accepted_types_narrows_deployment_wildcard():
    caps = OrchestratorCapabilities(
        deployment=_deployment(input_attachment_types=["*/*"]),  # type: ignore[arg-type]
        app_accepted_types=["image/*"],
    )

    assert caps.orchestrator_accepts_mime_type("image/png") is True
    assert caps.orchestrator_accepts_mime_type("application/pdf") is False


def test_app_accepted_types_cannot_widen_deployment_list():
    caps = OrchestratorCapabilities(
        deployment=_deployment(input_attachment_types=["application/pdf"]),  # type: ignore[arg-type]
        app_accepted_types=["image/*"],
    )

    assert caps.orchestrator_accepts_mime_type("image/png") is False
    assert caps.orchestrator_accepts_mime_type("application/pdf") is False


def test_advertised_input_attachment_types_defaults_to_deployment_list():
    caps = OrchestratorCapabilities(
        deployment=_deployment(input_attachment_types=["*/*"]),  # type: ignore[arg-type]
    )

    assert caps.advertised_input_attachment_types == ["*/*"]


def test_advertised_input_attachment_types_uses_app_narrowing_when_set():
    caps = OrchestratorCapabilities(
        deployment=_deployment(input_attachment_types=["*/*"]),  # type: ignore[arg-type]
        app_accepted_types=["image/*"],
    )

    assert caps.advertised_input_attachment_types == ["image/*"]


def test_advertised_input_attachment_types_uses_app_list_verbatim_even_without_deployment_overlap():
    # The deployment declares concrete types with no textual overlap against the
    # app's wildcard pattern; the advertised list is still the app's own list
    # verbatim — computing pattern-vs-pattern overlap correctly is exactly the
    # fiddly intersection problem this property deliberately avoids.
    caps = OrchestratorCapabilities(
        deployment=_deployment(  # type: ignore[arg-type]
            input_attachment_types=["image/png", "image/jpeg"]
        ),
        app_accepted_types=["image/*"],
    )

    assert caps.advertised_input_attachment_types == ["image/*"]
    # ...and the real gate still correctly accepts these concrete mimes, even
    # though the advertised pattern and the deployment's concrete list don't
    # textually match.
    assert caps.orchestrator_accepts_mime_type("image/png") is True
