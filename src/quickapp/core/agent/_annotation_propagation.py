"""Anchor-survival filtering for citation annotations propagated to the choice.

An annotation is not self-contained: it points into text via a ``<cit id="...">``
anchor. What reaches the choice is the orchestrator's answer, not the tool's, so
annotations whose anchor did not survive rewriting are dropped.
"""

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

_ANCHOR_RE = re.compile(r'<cit\s+id="([^"]+)"')
_ID_TOKEN_RE = re.compile(r"[0-9A-Za-z_-]+")


class PendingAnnotation(BaseModel):
    """An annotation plus the anchor ids it was resolved against in the tool's answer."""

    model_config = ConfigDict(frozen=True)

    payload: dict[str, Any]
    anchor_ids: frozenset[str]


def anchor_ids_in_text(text: str) -> set[str]:
    """Collect the ids of every ``<cit id="...">`` anchor present in ``text``."""
    return set(_ANCHOR_RE.findall(text or ""))


def resolve_pending(annotations: list[dict[str, Any]], content: str) -> list[PendingAnnotation]:
    """Pair each annotation with the anchors of ``content`` its target actually references.

    Matching is deliberately shape-agnostic — the selector format is owned by the
    annotation producer, so every string under ``target`` is scanned for id tokens and
    intersected with the anchors the producer itself emitted. That intersection filters
    out incidental tokens (selector type names, URLs) which are not anchor ids.
    """
    known_ids = anchor_ids_in_text(content)
    return [
        PendingAnnotation(
            payload=annotation,
            anchor_ids=frozenset(_target_id_tokens(annotation) & known_ids),
        )
        for annotation in annotations
    ]


def _target_id_tokens(annotation: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    _collect_id_tokens(annotation.get("target"), ids)
    return ids


def _collect_id_tokens(node: Any, ids: set[str]) -> None:
    if isinstance(node, str):
        ids.update(_ID_TOKEN_RE.findall(node))
    elif isinstance(node, dict):
        for value in node.values():
            _collect_id_tokens(value, ids)
    elif isinstance(node, list):
        for item in node:
            _collect_id_tokens(item, ids)


def keep_anchored(
    pending: list[PendingAnnotation], surviving_ids: set[str]
) -> list[dict[str, Any]]:
    """Drop annotations whose anchor is missing from the final answer, and deduplicate.

    An annotation that resolved to no anchor at all is kept: an unrecognized selector
    shape must not silently discard evidence.
    """
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in pending:
        if item.anchor_ids and not (item.anchor_ids & surviving_ids):
            continue
        if not item.anchor_ids:
            logger.debug("Annotation resolved to no anchor id; keeping it")
        key = json.dumps(item.payload, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        kept.append(item.payload)
    return kept
