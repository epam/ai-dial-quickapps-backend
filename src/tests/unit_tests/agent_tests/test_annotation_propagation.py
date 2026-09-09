"""Tests for ``quickapp.core.agent._annotation_propagation``."""

from quickapp.core.agent._annotation_propagation import (
    anchor_ids_in_text,
    keep_anchored,
    resolve_pending,
)

TOOL_ANSWER = 'Alpha <cit id="e37335"> and beta <cit  id="a1b2c3">.'


def _annotation(selector_value: str, quote: str = "quote") -> dict:
    return {
        "target": {"selector": {"type": "CssSelector", "value": selector_value}},
        "body": {"title": "Doc", "quote": quote, "source": {"url": "https://example/doc"}},
    }


def test_anchor_ids_in_text_collects_every_anchor():
    assert anchor_ids_in_text(TOOL_ANSWER) == {"e37335", "a1b2c3"}


def test_anchor_ids_in_text_empty():
    assert anchor_ids_in_text("") == set()
    assert anchor_ids_in_text("no anchors here") == set()


def test_resolve_pending_keeps_only_ids_the_tool_actually_anchored():
    [pending] = resolve_pending([_annotation("cit#e37335")], TOOL_ANSWER)

    # "CssSelector" and the source URL are incidental tokens, not anchor ids.
    assert pending.anchor_ids == frozenset({"e37335"})


def test_resolve_pending_ignores_body_tokens():
    [pending] = resolve_pending([_annotation("cit#e37335", quote="a1b2c3")], TOOL_ANSWER)

    assert pending.anchor_ids == frozenset({"e37335"})


def test_resolve_pending_unrecognized_selector_resolves_to_nothing():
    annotation = {"target": {"selector": {"type": "XPathSelector", "value": "/div[2]/p[1]"}}}

    [pending] = resolve_pending([annotation], TOOL_ANSWER)

    assert pending.anchor_ids == frozenset()


def test_keep_anchored_keeps_surviving_annotation():
    annotation = _annotation("cit#e37335")
    pending = resolve_pending([annotation], TOOL_ANSWER)

    assert keep_anchored(pending, {"e37335"}) == [annotation]


def test_keep_anchored_drops_dangling_annotation():
    pending = resolve_pending([_annotation("cit#e37335")], TOOL_ANSWER)

    assert keep_anchored(pending, {"a1b2c3"}) == []


def test_keep_anchored_keeps_annotation_with_unrecognized_selector():
    annotation = {"target": {"selector": {"type": "XPathSelector", "value": "/div[2]/p[1]"}}}
    pending = resolve_pending([annotation], TOOL_ANSWER)

    assert keep_anchored(pending, set()) == [annotation]


def test_keep_anchored_keeps_annotation_without_target():
    annotation = {"body": {"quote": "q"}}
    pending = resolve_pending([annotation], TOOL_ANSWER)

    assert keep_anchored(pending, {"e37335"}) == [annotation]


def test_keep_anchored_deduplicates_identical_annotations():
    annotation = _annotation("cit#e37335")
    pending = resolve_pending([annotation, dict(annotation)], TOOL_ANSWER)

    assert keep_anchored(pending, {"e37335"}) == [annotation]


def test_keep_anchored_mixed_batch():
    kept = _annotation("cit#e37335")
    dropped = _annotation("cit#a1b2c3")
    pending = resolve_pending([kept, dropped], TOOL_ANSWER)

    assert keep_anchored(pending, {"e37335"}) == [kept]
