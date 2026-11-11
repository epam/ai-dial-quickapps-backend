import logging
from collections.abc import Sequence
from functools import cache
from typing import Literal

from openai.types.shared_params import ResponseFormatJSONSchema
from openai.types.shared_params.response_format_json_schema import JSONSchema
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary

logger = logging.getLogger(__name__)

SelectionKind = Literal["tool", "toolset"]
CatalogItem = DeferredToolCatalogEntry | DeferredToolsetSummary

_SYSTEM_PROMPT = (
    "You are a routing assistant. Given a user request, pick the {kind}s from the catalog below "
    "that can help to fulfil it: at most {limit}, best match first. "
    "Pick only {kind}s that clearly fit; if none fits, return no matches. "
    'Respond with a JSON object {{"matches": [{{"name": "<{kind} name>", "score": <number 0..1>}}]}} '
    "only, where name is written exactly as in the catalog and score is how well the {kind} fits "
    "the request (1 is a perfect fit). No explanation, no markdown.\n\n"
    "Catalog:\n{catalog}"
)
_USER_PROMPT = (
    "Request: {query}\n\n"
    'Answer with a JSON object like {{"matches": [{{"name": "name_a", "score": 0.9}}]}}, '
    'or {{"matches": []}} if none fits.'
)
_MATCHES_KEY = "matches"
_RESPONSE_FORMAT_NAME = "tool_routing"


class ScoredName(BaseModel):
    # `forbid` makes the generated JSON schema `additionalProperties: false`, which strict
    # structured output requires.
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    # `allow_inf_nan=False` is validation-only: it does not appear in the JSON schema
    score: float = Field(allow_inf_nan=False)


class RoutingSelection(BaseModel):
    """The structured routing answer; its JSON schema is the request's `response_format`."""

    model_config = ConfigDict(extra="forbid")

    matches: list[ScoredName]


def render_catalog_line(entry: CatalogItem) -> str:
    return f"- {entry['name']}: {entry['description'] or ''}"


def build_system_prompt(catalog: Sequence[CatalogItem], kind: SelectionKind, limit: int) -> str:
    return _SYSTEM_PROMPT.format(
        kind=kind,
        limit=limit,
        catalog="\n".join(render_catalog_line(entry) for entry in catalog),
    )


def build_user_prompt(query: str) -> str:
    return _USER_PROMPT.format(query=query)


@cache
def build_response_format() -> ResponseFormatJSONSchema:
    """The `response_format` that makes the model answer `{"matches": [{"name", "score"}]}`.

    Names are plain strings, not an `enum` of the catalog: providers cap the schema size, and a
    large catalog would be rejected. The score range, the limit and unknown names are not
    expressed in the schema: `parse_selection` enforces all three.
    """
    schema = RoutingSelection.model_json_schema()
    # Inline the item definition: not every provider resolves `$ref`.
    schema["properties"][_MATCHES_KEY]["items"] = schema.pop("$defs")[ScoredName.__name__]
    return ResponseFormatJSONSchema(
        type="json_schema",
        json_schema=JSONSchema(name=_RESPONSE_FORMAT_NAME, strict=True, schema=schema),
    )


def parse_selection(
    raw: str, known_names: set[str], *, limit: int, threshold: float
) -> list[ScoredName]:
    """Validate the structured answer, then keep the best score per known name above `threshold`.

    An answer that does not match the schema (the provider ignored `response_format`) yields `[]`.
    """
    try:
        selection = RoutingSelection.model_validate_json(raw)
    except ValidationError:
        logger.warning("Routing call returned an answer that does not match the schema")
        return []

    best_scores: dict[str, float] = {}
    for match in selection.matches:
        score = min(max(match.score, 0.0), 1.0)
        if match.name in known_names and score >= threshold:
            best_scores[match.name] = max(score, best_scores.get(match.name, 0.0))

    ranked = sorted(best_scores.items(), key=lambda pair: pair[1], reverse=True)
    return [ScoredName(name=name, score=score) for name, score in ranked[:limit]]
