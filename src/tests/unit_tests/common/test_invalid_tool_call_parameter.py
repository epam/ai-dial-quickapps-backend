import logging

from quickapp.common.exceptions import InvalidToolCallParameterException


class TestMessageLengthBackstop:
    """Every one of these messages is fed back to the model as a retry instruction and
    rendered into the tool stage, so the message itself is capped regardless
    of whether the raising call site remembered to sanitize what it interpolated."""

    def test_oversized_message_truncated_with_notice(self):
        exc = InvalidToolCallParameterException(parameter_name="data", message="x" * 5000)

        assert exc.message.startswith("x" * 4000 + "…")
        assert "x" * 4001 not in exc.message
        assert exc.message.endswith("[message truncated: 4000 of 5000 chars shown]")
        assert str(exc) == exc.message

    def test_message_at_budget_untouched(self):
        message = "x" * 4000
        exc = InvalidToolCallParameterException(parameter_name="data", message=message)

        assert exc.message == message

    def test_message_within_budget_untouched(self):
        message = "Parameter `query` must be a string."
        exc = InvalidToolCallParameterException(parameter_name="query", message=message)

        assert exc.message == message

    def test_parameter_name_preserved_when_truncating(self):
        exc = InvalidToolCallParameterException(
            parameter_name="attachment_urls", message="y" * 5000
        )

        assert exc.parameter_name == "attachment_urls"

    def test_truncation_logs_warning_without_message_content(self, caplog):
        with caplog.at_level(logging.WARNING, logger="quickapp.common.exceptions"):
            InvalidToolCallParameterException(parameter_name="data", message="z" * 5000)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.WARNING
        assert "data" in record.getMessage()
        assert "z" * 10 not in record.getMessage()
