from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)


def _make_function(name: str, description: str = "desc") -> OpenAiToolFunction:
    return OpenAiToolFunction(
        name=name,
        description=description,
        parameters=OpenAiToolFunctionParameters(type=JsonTypeEnum.object, properties={}),
    )


class TestSetNameValidator:
    def test_appends_hash_suffix(self):
        func = _make_function("my_tool")
        assert func.name.startswith("my_tool_")
        assert len(func.name) == len("my_tool") + 5  # base + _ + 4 hex chars

    def test_hash_is_stable(self):
        func1 = _make_function("my_tool")
        func2 = _make_function("my_tool")
        assert func1.name == func2.name

    def test_different_params_produce_different_hashes(self):
        func1 = _make_function("my_tool", description="desc A")
        func2 = _make_function("my_tool", description="desc B")
        assert func1.name != func2.name
        assert func1.name[: len("my_tool")] == func2.name[: len("my_tool")]

    def test_idempotent_on_revalidation(self):
        func = _make_function("my_tool")
        hashed_name = func.name
        func2 = OpenAiToolFunction.model_validate(func.model_dump())
        assert func2.name == hashed_name

    def test_strips_whitespace(self):
        func = _make_function("  my_tool  ")
        assert not func.name.startswith(" ")
        assert not func.name.endswith(" ")
        # Should produce the same result as the trimmed version
        func_trimmed = _make_function("my_tool")
        assert func.name == func_trimmed.name

    def test_long_name_truncated_to_fit_64_chars(self):
        long_name = "a" * 70
        func = _make_function(long_name)
        assert len(func.name) == 64
        assert func.name.endswith(f"_{func.name[-4:]}")

    def test_exactly_59_char_name_fits_without_truncation(self):
        name = "a" * 59
        func = _make_function(name)
        assert len(func.name) == 64
        assert func.name.startswith(name)

    def test_exactly_60_char_name_truncated(self):
        name = "a" * 60
        func = _make_function(name)
        assert len(func.name) == 64
        # base must have been truncated to 59 chars
        assert func.name[:59] == name[:59]

    def test_name_coincidentally_ending_with_hex_chars_still_hashed(self):
        """A name ending with 4 hex chars (without underscore) must still get hashed."""
        func = _make_function("tool_setup")
        # Extract the hash that would be computed
        suffix = func.name[len("tool_setup") :]
        assert suffix.startswith("_")
        # The full name should be base + _hash, not the original
        assert func.name != "tool_setup"

    def test_max_length_never_exceeded(self):
        for length in [1, 10, 50, 59, 60, 64, 100, 200]:
            func = _make_function("x" * length)
            assert len(func.name) <= 64
