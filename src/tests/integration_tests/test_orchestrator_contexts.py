"""Integration tests for lazy admin file context (list + ``internal_attachments_get_content``)."""

from pathlib import Path

import pytest

from tests.integration_tests.test_runner.e2e_runner import e2e_test
from tests.integration_tests.test_runner.models import ToolCall, TstCase
from tests.integration_tests.test_runner.utils.tool_names import ToolNames

_DOCS = Path(__file__).parent / "test_documents"

# Deployments that accept PDF input attachments well enough for this scenario (extend as needed).
_LAZY_CONTEXT_MODELS = [
    "gpt-5.2-2025-12-11",
    "gpt-5-2025-08-07",
    "anthropic.claude-opus-4-6-v1",
]


@pytest.mark.integration
@e2e_test(
    config_file_set="lazy_admin_context",
    models_applicable_for_test=_LAZY_CONTEXT_MODELS,
    runs=1,
    include_rest_toolset=False,
    application_context_files=[
        _DOCS / "ontologies.pdf",
        _DOCS / "weo.pdf",
    ],
    test_case=TstCase(
        "Lazy admin context (PDF)",
        "Two admin PDFs; model must list then get_content the ontology doc only",
        similarity_threshold=0.72,
    ).add_user_message(
        user_message=(
            "Admin context includes two PDF files: one about ontology tooling and one IMF WEO. "
            "Answer using ONLY the internal tools `internal_attachments_available_context` and "
            "`internal_attachments_get_content` — first discover files, then load the ontology "
            "guide PDF (not the WEO). Do not use web search, RAG, code interpreter, or any other tools. "
            "Question: what are the tools to use when working with ontologies? "
            "Reply with a numbered list 1. Name 2. Name … only."
        ),
        tool_calls=[
            ToolCall(
                ToolNames.INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT.value, min_calls=1, max_calls=4
            ),
            ToolCall(ToolNames.INTERNAL_ATTACHMENTS_GET_CONTENT.value, min_calls=1, max_calls=4),
        ],
        answer=[
            """Based on the ontology guide PDF, here is the numbered list of tools to use when working with ontologies:
            1. Protégé
            2. OWL API
            3. Jena
            4. RDF4J
            5. SWRL
            6. SPARQL
            7. SHACL
            8. TopBraid Composer
            9. OntoGraf
            10. VOWL""",
        ],
    ),
)
def test_lazy_admin_context_list_then_get_content(client):
    """Orchestrator lists admin files then loads the correct PDF; answer matches ontology doc."""
