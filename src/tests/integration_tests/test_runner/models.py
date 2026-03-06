import datetime
from abc import ABC, abstractmethod
from pathlib import Path
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from tests.integration_tests.test_runner.config import SimilarityThreshold
from tests.integration_tests.test_runner.similarity_checker import get_similarity, get_similarity_alternatives


class Failure(BaseModel):
    actual: Any | None
    expected: Any | None
    comment: str | None
    similarity: str = None

    def _format_expected(self):
        if isinstance(self.expected, str):
            return repr(self.expected)
        if isinstance(self.expected, dict):
            formatted_items = " , ".join(
                "'{}': {}".format(k, str(v)) for k, v in self.expected.items()
            )
            return f"{{{formatted_items}}}"
        return str(self.expected)

    def __str__(self):
        similarity_str = f'[{self.similarity}]' if self.similarity else ''
        message = f"{self.comment}{similarity_str}"
        if self.expected or self.actual:
            message += f" Expected '{self._format_expected()}', got '{self.actual}'"
        return message


class BaseCheck(ABC):
    def __init__(self, similarity_threshold: float = SimilarityThreshold.DEFAULT.value):
        self.similarity_threshold = similarity_threshold

    @abstractmethod
    def check(self, actual_value: Any) -> list[Failure]:
        pass


class Argument(BaseCheck, ABC):
    def __init__(self, name: str, failure_message: str = None, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.failure_message = failure_message or f"Argument {name}:"

    def __str__(self):
        return f"name='{self.name}', failure_message='{self.failure_message}'"


class StrictArgument(Argument):
    def __init__(self, name: str, value: str, **kwargs):
        super().__init__(name, **kwargs)
        self.expected_value = value

    def check(self, actual_value: str) -> list[Failure]:
        if self.expected_value != actual_value:
            return [
                Failure(
                    actual=actual_value,
                    expected=self.expected_value,
                    comment=self.failure_message,
                )
            ]
        return []

    def __str__(self):
        base_str = super().__str__()
        return f"StrictArgument({base_str}, expected_value='{self.expected_value}')"


class SoftArgument(Argument):
    def __init__(self, name: str, values: list[str], **kwargs):
        super().__init__(name, **kwargs)
        self.expected_values = values

    def check(self, actual_value: str) -> list[Failure]:
        return check_multiple_alternatives(
            actual_value, self.expected_values, self.failure_message, self.similarity_threshold
        )

    def __str__(self):
        base_str = super().__str__()
        return f"SoftArgument({base_str}, expected_value='{self.expected_values}')"


class CustomFunctionArgument(Argument):
    def __init__(self, name: str, values: list[str], func: Callable[[str, str], bool], **kwargs):
        super().__init__(name, **kwargs)
        self.expected_values = values
        self.custom_function = func

    def check(self, actual_value: str) -> list[Failure]:
        return [
            Failure(
                actual=actual_value,
                expected=self.expected_values,
                comment=self.failure_message,
            )
            for expected_value in self.expected_values
            if not self.custom_function(actual_value, expected_value)
        ]

    def __str__(self):
        base_str = super().__str__()
        return f"CustomFunctionArgument({base_str}, expected_values='{self.expected_values}', func={self.custom_function})"


class ToolCall:
    def __init__(
        self,
        name: str,
        similarity_threshold: float = SimilarityThreshold.DEFAULT.value,
        min_calls: int = 1,
        max_calls: int = 1,
    ):
        self.name = name
        self.min_calls = min_calls
        self.max_calls = max_calls
        self.arguments: dict[str, Argument] = {}
        self.similarity_threshold = similarity_threshold

    def add_soft_argument_check(
        self, name: str, value: list[str], similarity_threshold: float = None
    ):
        if not similarity_threshold:
            similarity_threshold = self.similarity_threshold
        self.arguments[name] = SoftArgument(name, value, similarity_threshold=similarity_threshold)
        return self

    def add_strict_argument_check(self, name: str, value: Any):
        self.arguments[name] = StrictArgument(name, str(value))
        return self

    def add_custom_function_argument_check(
        self, name: str, value: list[str], func: Callable[[str, str], bool]
    ):
        self.arguments[name] = CustomFunctionArgument(name, value, func=func)
        return self

    def __str__(self):
        arguments_str = ", ".join(f"{key}: {value}" for key, value in self.arguments.items())
        return (
            f"ToolCall(name='{self.name}', "
            f"min_calls={self.min_calls}, max_calls={self.max_calls}, "
            f"similarity_threshold={self.similarity_threshold:.2f}, "
            f"arguments={{ {arguments_str} }})"
        )


class AttachmentCheck(BaseModel):
    """Represents checks to perform on attachments."""

    title_strict: str | None = None
    title_soft: str | list[str] | None = None
    type: str | None = None
    similarity_threshold: float = SimilarityThreshold.DEFAULT.value

    def model_post_init(self, __context: Any) -> None:
        if isinstance(self.title_soft, str):
            object.__setattr__(self, "title_soft", [self.title_soft])


class UserMessage(BaseModel):
    """Represents a user message with associated tool calls and attachment checks."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_message: str
    attachments: list[Path] | None = None
    tool_calls: list[ToolCall] | None = None
    attachment_checks: list[AttachmentCheck] | None = None
    answer: list[str] | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.attachments is None:
            object.__setattr__(self, "attachments", [])
        if self.tool_calls is None:
            object.__setattr__(self, "tool_calls", [])
        if self.attachment_checks is None:
            object.__setattr__(self, "attachment_checks", [])


class TstCase:
    def __init__(
        self,
        name: str,
        description: str,
        similarity_threshold: float = SimilarityThreshold.DEFAULT.value,
        response_format: dict[str, Any] | None = None,
    ):
        self.name = name
        self.description = description
        self.messages: list[UserMessage] = []
        self.mock_date = datetime.date.today()
        self.similarity_threshold = similarity_threshold
        self.py_interpreter_session_flow = False
        self.response_format = response_format

    def add_user_message(
        self,
        user_message: str,
        attachments: list[Path] | None = None,
        tool_calls: list[ToolCall] | None = None,
        attachment_checks: list[AttachmentCheck] | None = None,
        answer: list[str] | None = None,
    ):
        tool_calls, attachment_checks = self._adjust_thresholds(tool_calls, attachment_checks)
        self.messages.append(
            UserMessage(
                user_message=user_message,
                attachments=attachments,
                tool_calls=tool_calls,
                attachment_checks=attachment_checks,
                answer=answer,
            )
        )
        return self

    def _adjust_thresholds(self, tool_calls: list[ToolCall], attachments: list[AttachmentCheck]):
        if tool_calls:
            for tool_call in tool_calls:
                if tool_call.similarity_threshold == SimilarityThreshold.DEFAULT.value:
                    tool_call.similarity_threshold = self.similarity_threshold
                for arg in tool_call.arguments.values():
                    if (
                        isinstance(arg, SoftArgument)
                        and arg.similarity_threshold == SimilarityThreshold.DEFAULT.value
                    ):
                        arg.similarity_threshold = self.similarity_threshold

        if attachments:
            for attachment in attachments:
                if attachment.similarity_threshold == SimilarityThreshold.DEFAULT.value:
                    attachment.similarity_threshold = self.similarity_threshold
        return tool_calls, attachments

    def add_mock_date(self, mock_date):
        self.mock_date = mock_date
        return self

    def add_py_interpreter_session_flow(self):
        self.py_interpreter_session_flow = True
        return self


def check_multiple_alternatives(
    actual_value: str, expected_values: list[str], failure_message: str, similarity_threshold: float
) -> list[Failure]:
    """
    Check if actual value matches any of the expected values within similarity threshold.
    """
    failures = []
    similarity, max_similarity_alternative = get_similarity_alternatives(
        actual_value, expected_values
    )
    if similarity < similarity_threshold:
        failures.append(
            Failure(
                actual=actual_value,
                expected=max_similarity_alternative,
                comment=failure_message,
                similarity=str(similarity),
            )
        )
    return failures


def check_similarity(
    actual: str, expected: str, failure_message: str, similarity_threshold: float
) -> list[Failure]:
    """
    Check similarity between actual and expected text.
    """
    failures = []
    similarity = get_similarity(actual, expected)
    if similarity < similarity_threshold:
        failures.append(
            Failure(
                actual=actual,
                expected=expected,
                comment=failure_message,
                similarity=str(similarity),
            )
        )
    return failures
