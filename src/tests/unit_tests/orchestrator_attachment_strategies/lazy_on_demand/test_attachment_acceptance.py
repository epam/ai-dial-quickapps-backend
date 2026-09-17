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


def test_advertised_input_attachment_types_drops_entries_the_deployment_can_never_accept():
    # accepted_types adds a top-level type the deployment doesn't declare at all;
    # advertising it would promise the model a file type every real call rejects.
    acceptance = _AttachmentAcceptance(
        _caps(["image/*"]), accepted_types=["image/*", "application/*"]
    )

    assert acceptance.advertised_input_attachment_types == ["image/*"]
    assert acceptance.accepts_mime_type("application/pdf") is False


def test_advertised_input_attachment_types_empty_when_deployment_accepts_nothing():
    acceptance = _AttachmentAcceptance(_caps(None), accepted_types=["image/*"])

    assert acceptance.advertised_input_attachment_types == []

    acceptance = _AttachmentAcceptance(_caps([]), accepted_types=["image/*"])

    assert acceptance.advertised_input_attachment_types == []


# --- Wide-vs-narrow deployment/accepted_types pairings ---
#
# Each pair below narrows in one direction: either the deployment declares a
# wildcard and accepted_types picks a specific mime out of it (accurate
# narrowing — the advertised list matches exactly what's really accepted), or
# the deployment declares a single concrete mime and accepted_types names a
# wildcard that happens to share its top-level type (a known tradeoff: the
# wildcard is kept verbatim even though the deployment only ever accepts that
# one exact mime — see the "verbatim_even_without_deployment_overlap" test
# above for why this property doesn't attempt full pattern intersection).


def test_wildcard_deployment_narrowed_to_one_specific_accepted_type():
    # orchestrator: "*/*"; lazy_on_demand: "application/vnd.plotly.v1+json"
    acceptance = _AttachmentAcceptance(
        _caps(["*/*"]), accepted_types=["application/vnd.plotly.v1+json"]
    )

    assert acceptance.advertised_input_attachment_types == ["application/vnd.plotly.v1+json"]
    assert acceptance.accepts_mime_type("application/vnd.plotly.v1+json") is True
    assert acceptance.accepts_mime_type("application/pdf") is False


def test_specific_deployment_widened_by_overlapping_wildcard_accepted_types():
    # orchestrator: "application/pdf"; lazy_on_demand: "application/*", "image/*"
    # "image/*" is dropped (no possible overlap with "application/pdf"), but
    # "application/*" is kept even though the deployment only ever accepts the
    # single concrete "application/pdf" mime.
    acceptance = _AttachmentAcceptance(
        _caps(["application/pdf"]), accepted_types=["application/*", "image/*"]
    )

    assert acceptance.advertised_input_attachment_types == ["application/*"]
    assert acceptance.accepts_mime_type("application/pdf") is True
    assert acceptance.accepts_mime_type("application/msword") is False
    assert acceptance.accepts_mime_type("image/png") is False


def test_wildcard_deployment_narrowed_to_one_concrete_accepted_type():
    # orchestrator: "image/*"; lazy_on_demand: "image/png"
    acceptance = _AttachmentAcceptance(_caps(["image/*"]), accepted_types=["image/png"])

    assert acceptance.advertised_input_attachment_types == ["image/png"]
    assert acceptance.accepts_mime_type("image/png") is True
    assert acceptance.accepts_mime_type("image/jpeg") is False


def test_specific_deployment_widened_by_overlapping_accepted_type_wildcard():
    # orchestrator: "application/vnd.plotly.v1+json"; lazy_on_demand: "application/*"
    # Same tradeoff as above from the other direction.
    acceptance = _AttachmentAcceptance(
        _caps(["application/vnd.plotly.v1+json"]), accepted_types=["application/*"]
    )

    assert acceptance.advertised_input_attachment_types == ["application/*"]
    assert acceptance.accepts_mime_type("application/vnd.plotly.v1+json") is True
    assert acceptance.accepts_mime_type("application/pdf") is False
