import json
import logging
import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary

logger = logging.getLogger(__name__)

SelectionKind = Literal["tool", "toolset"]
CatalogItem = DeferredToolCatalogEntry | DeferredToolsetSummary

_SYSTEM_PROMPT = (
    "You are a routing assistant. Given a user request, pick the {kind}s from the catalog below "
    "that can help to fulfil it: at most {limit}, best match first. "
    "Pick only {kind}s that clearly fit; if none fits, return an empty array. "
    'Respond with a JSON array of objects {{"name": "<{kind} name>", "score": <number 0..1>}} '
    "only, where name is written exactly as in the catalog and score is how well the {kind} "
    "fits the request (1 is a perfect fit). No explanation, no markdown.\n\n"
    "Catalog:\n{catalog}"
)
_USER_PROMPT = (
    "Request: {query}\n\n"
    'Answer with a JSON array like [{{"name": "name_a", "score": 0.9}}], or [] if none fits.'
)


class ScoredName(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    score: float


def render_catalog_line(entry: CatalogItem) -> str:
    return f"- {entry['name']}: {entry.get('description') or ''}"


def build_system_prompt(catalog: Sequence[CatalogItem], kind: SelectionKind, limit: int) -> str:
    return _SYSTEM_PROMPT.format(
        kind=kind,
        limit=limit,
        catalog="\n".join(render_catalog_line(entry) for entry in catalog),
    )


def build_user_prompt(query: str) -> str:
    return _USER_PROMPT.format(query=query)


def parse_selection(
    raw: str, known_names: set[str], *, limit: int, threshold: float
) -> list[ScoredName]:
    # find/rfind skip a surrounding Markdown fence and any chatter around the array
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end < start:
        logger.warning("Routing call returned no JSON array (length=%d)", len(raw))
        return []
    try:
        items = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("Routing call returned non-JSON response (length=%d)", len(raw))
        return []

    best_scores: dict[str, float] = {}
    for item in items:
        name, score = _read_item(item)
        if name is None or name not in known_names or score < threshold:
            continue
        best_scores[name] = max(score, best_scores.get(name, 0.0))

    ranked = sorted(best_scores.items(), key=lambda pair: pair[1], reverse=True)
    return [ScoredName(name=name, score=score) for name, score in ranked[:limit]]


def _read_item(item: object) -> tuple[str | None, float]:
    """A plain string is accepted and treated as a perfect fit (the model skipped the score)."""
    if isinstance(item, str):
        return item, 1.0
    if isinstance(item, dict) and isinstance(item.get("name"), str):
        try:
            score = float(item.get("score", 1.0))
        except (TypeError, ValueError, OverflowError):
            return item["name"], 1.0
        if math.isnan(score):
            return None, 0.0
        return item["name"], min(max(score, 0.0), 1.0)
    return None, 0.0
