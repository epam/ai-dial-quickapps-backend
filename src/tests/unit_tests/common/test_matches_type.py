from quickapp.common.utils import matches_type


class TestMatchesType:
    def test_none_mime_type_returns_false(self):
        assert matches_type(None, ["image/*"]) is False

    def test_none_allowed_mime_types_returns_false(self):
        assert matches_type("image/png", None) is False

    def test_both_none_returns_false(self):
        assert matches_type(None, None) is False

    def test_exact_match(self):
        assert matches_type("image/png", ["image/png"]) is True

    def test_no_match(self):
        assert matches_type("image/png", ["application/pdf"]) is False

    def test_wildcard_match(self):
        assert matches_type("image/png", ["image/*"]) is True
        assert matches_type("image/jpeg", ["image/*"]) is True

    def test_wildcard_no_match(self):
        assert matches_type("application/pdf", ["image/*"]) is False

    def test_catch_all_wildcard(self):
        assert matches_type("application/pdf", ["*/*"]) is True
        assert matches_type("image/png", ["*/*"]) is True

    def test_empty_allowed_list(self):
        assert matches_type("image/png", []) is False

    def test_multiple_allowed_types(self):
        allowed = ["image/*", "application/pdf"]
        assert matches_type("image/png", allowed) is True
        assert matches_type("application/pdf", allowed) is True
        assert matches_type("text/plain", allowed) is False