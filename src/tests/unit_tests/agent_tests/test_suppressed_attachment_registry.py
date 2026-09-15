"""Unit tests for SuppressedAttachmentRegistry."""

from quickapp.core.agent._suppressed_attachment_registry import SuppressedAttachmentRegistry


def test_is_suppressed_false_by_default():
    registry = SuppressedAttachmentRegistry()
    assert registry.is_suppressed("https://dial-core/uploads/file.png") is False


def test_is_suppressed_false_for_none_url():
    registry = SuppressedAttachmentRegistry()
    registry.suppress("https://dial-core/uploads/file.png")
    assert registry.is_suppressed(None) is False


def test_suppress_marks_url_as_suppressed():
    registry = SuppressedAttachmentRegistry()
    url = "https://dial-core/uploads/file.png"
    registry.suppress(url)
    assert registry.is_suppressed(url) is True


def test_suppress_does_not_affect_other_urls():
    registry = SuppressedAttachmentRegistry()
    registry.suppress("https://dial-core/uploads/suppressed.png")
    assert registry.is_suppressed("https://dial-core/uploads/other.png") is False


def test_unsuppress_clears_suppressed_url():
    registry = SuppressedAttachmentRegistry()
    url = "https://dial-core/uploads/file.png"
    registry.suppress(url)
    registry.unsuppress(url)
    assert registry.is_suppressed(url) is False


def test_unsuppress_is_noop_for_never_suppressed_url():
    registry = SuppressedAttachmentRegistry()
    url = "https://dial-core/uploads/file.png"
    registry.unsuppress(url)
    assert registry.is_suppressed(url) is False
