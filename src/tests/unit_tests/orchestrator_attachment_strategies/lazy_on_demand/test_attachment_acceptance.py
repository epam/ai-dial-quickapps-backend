from types import SimpleNamespace

import pytest

from quickapp.core.agent import OrchestratorCapabilities
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_acceptance import (
    _AttachmentAcceptance,
)


def _caps(input_attachment_types: list[str] | None) -> OrchestratorCapabilities:
    return OrchestratorCapabilities(
        deployment=SimpleNamespace(  # type: ignore[arg-type]
            id="gpt-4", input_attachment_types=input_attachment_types
        )
    )


def test_deployment_id_passthrough():
    acceptance = _AttachmentAcceptance(_caps(["application/pdf"]))

    assert acceptance.deployment_id == "gpt-4"


@pytest.mark.parametrize(
    "mime, expected",
    [
        ("application/pdf", True),
        ("image/png", True),
        ("text/csv", False),
    ],
)
def test_accepts_mime_type_matches_input_attachment_types(mime: str, expected: bool):
    acceptance = _AttachmentAcceptance(_caps(["application/pdf", "image/*"]))

    assert acceptance.accepts_mime_type(mime) is expected


def test_accepts_mime_type_returns_false_when_input_attachment_types_is_none():
    acceptance = _AttachmentAcceptance(_caps(None))

    assert acceptance.accepts_mime_type("application/pdf") is False
    assert acceptance.accepts_mime_type("image/png") is False


def test_accepted_types_narrows_deployment_wildcard():
    acceptance = _AttachmentAcceptance(_caps(["*/*"]), accepted_types=["image/*"])

    assert acceptance.accepts_mime_type("image/png") is True
    assert acceptance.accepts_mime_type("application/pdf") is False


def test_accepted_types_cannot_widen_deployment_list():
    acceptance = _AttachmentAcceptance(_caps(["application/pdf"]), accepted_types=["image/*"])

    assert acceptance.accepts_mime_type("image/png") is False
    assert acceptance.accepts_mime_type("application/pdf") is False


def test_advertised_input_attachment_types_defaults_to_deployment_list():
    acceptance = _AttachmentAcceptance(_caps(["*/*"]))

    assert acceptance.advertised_input_attachment_types == ["*/*"]


def test_advertised_input_attachment_types_uses_accepted_types_when_set():
    acceptance = _AttachmentAcceptance(_caps(["*/*"]), accepted_types=["image/*"])

    assert acceptance.advertised_input_attachment_types == ["image/*"]


def test_advertised_input_attachment_types_uses_accepted_types_verbatim_even_without_deployment_overlap():
    # The deployment declares concrete types with no textual overlap against the
    # app's wildcard pattern; the advertised list is still the app's own list
    # verbatim — computing pattern-vs-pattern overlap correctly is exactly the
    # fiddly intersection problem this property deliberately avoids.
    acceptance = _AttachmentAcceptance(
        _caps(["image/png", "image/jpeg"]), accepted_types=["image/*"]
    )

    assert acceptance.advertised_input_attachment_types == ["image/*"]
    # ...and the real gate still correctly accepts these concrete mimes, even
    # though the advertised pattern and the deployment's concrete list don't
    # textually match.
    assert acceptance.accepts_mime_type("image/png") is True
