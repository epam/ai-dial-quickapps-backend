"""Unit tests for deployment tool config: ContentPropagation."""

import pytest

from quickapp.config.tools.deployment import ContentPropagation


class TestContentPropagation:
    """ContentPropagation: default propagate_stages and parsing."""

    def test_default_propagate_stages_is_false(self):
        """Default propagate_stages must be False so propagation is opt-in."""
        cfg = ContentPropagation()
        assert cfg.propagate_stages is False

    def test_propagate_stages_true_parses_and_readable(self):
        """When propagate_stages is True, config parses and value is readable."""
        cfg = ContentPropagation(propagate_stages=True)
        assert cfg.propagate_stages is True

    def test_propagate_stages_with_other_fields(self):
        """ContentPropagation with propagate_stages and other fields parses correctly."""
        cfg = ContentPropagation(
            propagate_history=True,
            propagate_headers=["X-Custom"],
            propagate_stages=True,
        )
        assert cfg.propagate_history is True
        assert cfg.propagate_headers == ["X-Custom"]
        assert cfg.propagate_stages is True
