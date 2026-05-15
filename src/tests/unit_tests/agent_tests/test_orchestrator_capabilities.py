from types import SimpleNamespace

import pytest

from quickapp.agent.orchestrator_capabilities import OrchestratorCapabilities


def _deployment(
    deployment_id: str = "gpt-4",
    input_attachment_types: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(id=deployment_id, input_attachment_types=input_attachment_types)


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
