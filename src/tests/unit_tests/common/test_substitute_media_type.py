from quickapp.common.utils import substitute_media_type


class TestSubstituteMediaType:
    def test_none_mime_type_returns_none(self):
        assert substitute_media_type(None, {"image/png": "image/webp"}) is None

    def test_empty_mapping_returns_original(self):
        assert substitute_media_type("image/png", {}) == "image/png"

    def test_no_match_returns_original(self):
        assert substitute_media_type("image/png", {"text/plain": "text/html"}) == "image/png"

    def test_exact_match_substitutes(self):
        assert substitute_media_type("image/png", {"image/png": "image/webp"}) == "image/webp"

    def test_multiple_mappings(self):
        mapping = {
            "image/png": "image/webp",
            "text/plain": "text/html",
        }
        assert substitute_media_type("image/png", mapping) == "image/webp"
        assert substitute_media_type("text/plain", mapping) == "text/html"
        assert substitute_media_type("application/pdf", mapping) == "application/pdf"
