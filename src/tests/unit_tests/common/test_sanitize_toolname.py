from quickapp.common.utils import sanitize_toolname


class TestSanitizeToolname:

    def test_spaces_replaced_with_underscore(self):
        assert sanitize_toolname("my tool name") == "my_tool_name"

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
