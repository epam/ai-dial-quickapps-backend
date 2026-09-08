from quickapp.common.utils import sanitize_toolname


class TestSanitizeToolname:

    def test_spaces_replaced_with_underscore(self):
        assert sanitize_toolname("my tool name") == "my_tool_name"

    def test_multiple_slash_replaced_with_underscore(self):
        assert sanitize_toolname("my//tool//name") == "my_tool_name"

    def test_slashes_replaced_with_underscore(self):
        assert sanitize_toolname("applications/public/my-app") == "applications_public_my-app"

    def test_periods_replaced_with_underscore(self):
        assert sanitize_toolname("my_app_1.0") == "my_app_1_0"

    def test_alphanumeric_hyphen_underscore_unchanged(self):
        assert sanitize_toolname("my-valid_tool123") == "my-valid_tool123"

    def test_truncates_at_64_chars(self):
        long_name = "a" * 70
        assert sanitize_toolname(long_name) == "a" * 64

    def test_real_display_name_with_spaces(self):
        assert (
            sanitize_toolname("App with fetch and internal docs")
            == "App_with_fetch_and_internal_docs"
        )

    def test_empty_string_returns_empty(self):
        assert sanitize_toolname("") == ""

    def test_leading_digit_prefixed_with_underscore(self):
        assert sanitize_toolname("27.03 notion toolset") == "_27_03_notion_toolset"

    def test_sanitizing_twice_is_idempotent(self):
        once = sanitize_toolname("123abc")
        assert sanitize_toolname(once) == once == "_123abc"

    def test_leading_hyphen_prefixed_with_underscore(self):
        assert sanitize_toolname("-notion toolset") == "_-notion_toolset"

    def test_leading_letter_not_prefixed(self):
        assert sanitize_toolname("abc123") == "abc123"

    def test_leading_underscore_not_prefixed(self):
        assert sanitize_toolname("_abc123") == "_abc123"

    def test_truncates_at_64_chars_after_leading_digit_prefix(self):
        long_name = "1" + "a" * 70
        assert sanitize_toolname(long_name) == "_1" + "a" * 62
