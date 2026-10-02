from quickapp.common.exceptions import InvalidToolCallParameterException


class TestMessageLengthBackstop:
    """Every one of these messages is fed back to the model as a retry instruction and
    rendered into the tool stage, so the message itself is capped (issue #578) regardless
    of whether the raising call site remembered to sanitize what it interpolated."""

    def test_oversized_message_truncated_with_marker(self):
        exc = InvalidToolCallParameterException(parameter_name="data", message="x" * 5000)

        assert exc.message.startswith("x" * 1000)
        assert exc.message.endswith("…")
        assert str(exc) == exc.message

    def test_message_within_budget_untouched(self):
        message = "Parameter `query` must be a string."
        exc = InvalidToolCallParameterException(parameter_name="query", message=message)

        assert exc.message == message

    def test_parameter_name_preserved_when_truncating(self):
        exc = InvalidToolCallParameterException(
            parameter_name="attachment_urls", message="y" * 2000
        )

        assert exc.parameter_name == "attachment_urls"
