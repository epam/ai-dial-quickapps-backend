import logging

logger = logging.getLogger(__name__)

# Caps the message fed back to the model so it can't overflow the next request.
_MAX_MESSAGE_LENGTH = 4000  # Hyperparameter


class InvalidToolCallParameterException(ValueError):

    def __init__(self, parameter_name: str, message: str):
        if len(message) > _MAX_MESSAGE_LENGTH:
            logger.warning(
                "Truncated error message for parameter %s from %d to %d chars",
                parameter_name,
                len(message),
                _MAX_MESSAGE_LENGTH,
            )
            message = (
                f"{message[:_MAX_MESSAGE_LENGTH]}… "
                f"[message truncated: {_MAX_MESSAGE_LENGTH} of {len(message)} chars shown]"
            )
        super().__init__(message)
        self.parameter_name = parameter_name
        self.message = message
