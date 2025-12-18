import json
import logging
from typing import Dict, List, NamedTuple, Any

from quickapp.agent.models import TOOL_EXECUTION_HISTORY, ExecutedToolCallDTO
from tests.conftest import FailureReason, TestStats
from tests.test_runner.models import Argument, AttachmentCheck, Failure, ToolCall
from tests.test_runner.similarity_checker import get_similarity, get_similarity_alternatives

logger = logging.getLogger(__name__)


class ParsedToolCall(NamedTuple):
    """A simple data structure to hold the essential information from a tool call."""

    name: str
    args: Dict[str, Any]
    result: str


class ResponseValidator:
    """
    Validates responses against expected tool calls, arguments, and attachments.
    """

    @staticmethod
    def _parse_intermediate_steps(state: Dict) -> List[ParsedToolCall]:
        """
        Parses the 'intermediate_steps' string from the state into a list of ParsedToolCall objects.
        The new state format is a JSON string of a list of tuples, where each tuple contains
        (ToolAgentAction, tool_output).
        """
        if state is None:
            return []
        steps = state.get(TOOL_EXECUTION_HISTORY)
        if not steps:
            return []

        try:
            # The outer structure is a JSON array
            parsed_calls = []

            for step in steps:
                tool_call_dto = ExecutedToolCallDTO(**step)
                tool_name = tool_call_dto.tool_call.function.name
                tool_input = tool_call_dto.tool_call.function.arguments

                if isinstance(tool_input, str):
                    try:
                        args = json.loads(tool_input)
                    except json.JSONDecodeError:
                        args = {"input": tool_input}
                else:
                    args = tool_input or {}

                result_content = tool_call_dto.tool_execution_result.content

                if tool_name:
                    parsed_calls.append(
                        ParsedToolCall(name=tool_name, args=args, result=result_content)
                    )

            return parsed_calls
        except (json.JSONDecodeError, TypeError, IndexError) as e:
            print(f"Error parsing intermediate_steps: {e}")
            return []

    @staticmethod
    def check_similarity(
        actual: str, expected: str, failure_message: str, similarity_threshold: float
    ) -> List[Failure]:
        """
        Checks if the similarity between actual and expected text meets the threshold.

        Args:
            actual (str): Actual text.
            expected (str): Expected text.
            failure_message (str): Message for failure.
            similarity_threshold (float): Minimum similarity required.

        Returns:
            List[Failure]: List of failures if similarity is below threshold.
        """
        failures = []
        similarity = get_similarity(actual, expected)
        if similarity < similarity_threshold:
            failures.append(Failure(actual, expected, failure_message, str(similarity)))
        return failures

    @staticmethod
    def check_tool_calls(
            state: Dict, expected_tool_calls: List[ToolCall], ts: TestStats
    ) -> List[Failure]:
        """
        Validates tool calls in the response against expected calls.
        """
        failures = []
        tool_call_history = ResponseValidator._parse_intermediate_steps(state)

        # Filter out failed py_code_interpreter calls
        tool_call_history = ResponseValidator._filter_py_code_interpreter(tool_call_history)

        # Validate tool call counts
        failures.extend(
            ResponseValidator._validate_tool_call_counts(
                tool_call_history, expected_tool_calls, ts
            )
        )

        # Validate tool call arguments
        failures.extend(
            ResponseValidator._validate_tool_call_arguments(
                tool_call_history, expected_tool_calls, ts
            )
        )

        # Check for unexpected tool calls
        failures.extend(
            ResponseValidator._check_unexpected_tools(tool_call_history, expected_tool_calls, ts)
        )

        return failures

    @staticmethod
    def _filter_py_code_interpreter(
            tool_call_history: List[ParsedToolCall],
    ) -> List[ParsedToolCall]:
        """
        Filters out failed py_code_interpreter tool calls.
        Adapted to use the ParsedToolCall structure.
        """
        return [
            tool_call
            for tool_call in tool_call_history
            if not (
                    tool_call.name == 'py_code_interpreter'
                    and (
                            "FAILURE" in tool_call.result
                            or "Python Code Interpreter session has been closed"
                            in tool_call.result
                    )
            )
        ]

    @staticmethod
    def _validate_tool_call_counts(
            tool_call_history: List[ParsedToolCall],
            expected_tool_calls: List[ToolCall],
            ts: TestStats,
    ) -> List[Failure]:
        """
        Validates the count of each tool call.
        Adapted to use the ParsedToolCall structure.
        """
        failures = []
        for expected in expected_tool_calls:
            matched_calls = [
                tool_call for tool_call in tool_call_history if tool_call.name == expected.name
            ]
            call_count = len(matched_calls)
            if call_count < expected.min_calls:
                failures.append(
                    Failure(
                        call_count,
                        f"{expected.min_calls}-{expected.max_calls}",
                        f"'{expected.name}' called {call_count} times (min {expected.min_calls} required)",
                    )
                )
                ts.increment_failure(FailureReason.TOOL_CALL_COUNT)
            if call_count > expected.max_calls:
                failures.append(
                    Failure(
                        call_count,
                        f"{expected.min_calls}-{expected.max_calls}",
                        f"'{expected.name}' called {call_count} times (max {expected.max_calls} allowed)",
                    )
                )
                ts.increment_failure(FailureReason.TOOL_CALL_COUNT)
        return failures

    @staticmethod
    def _validate_tool_call_arguments(
            tool_call_history: List[ParsedToolCall],
            expected_tool_calls: List[ToolCall],
            ts: TestStats,
    ) -> List[Failure]:
        """
        Validates the arguments of each tool call.
        Adapted to use the ParsedToolCall structure.
        """
        failures = []
        for expected in expected_tool_calls:
            found_match = False
            # Find at least one actual call that satisfies the expected argument checks
            for actual in tool_call_history:
                if actual.name != expected.name:
                    continue

                arg_failures = ResponseValidator.check_arguments(
                    actual_tool_call=actual, expected_arguments=expected.arguments, ts=ts
                )
                if not arg_failures:
                    found_match = True
                    break  # Found a valid call, no need to check other calls for this expectation

            if not found_match:
                failures.append(
                    Failure(
                        actual=[call._asdict() for call in tool_call_history],
                        expected=expected.arguments,
                        comment=f"No matching call for '{expected.name}' found with the required arguments.",
                    )
                )
                ts.increment_failure(FailureReason.ARGUMENTS)
        return failures

    @staticmethod
    def _check_unexpected_tools(
            tool_call_history: List[ParsedToolCall],
            expected_tool_calls: List[ToolCall],
            ts: TestStats,
    ) -> List[Failure]:
        """
        Checks for unexpected tool calls.
        """
        failures = []
        expected_names = {tc.name for tc in expected_tool_calls}
        for actual in tool_call_history:
            if actual.name not in expected_names:
                failures.append(
                    Failure(
                        actual.name,
                        "No unexpected tools",
                        f"Unexpected tool '{actual.name}' called",
                    )
                )
                ts.increment_failure(FailureReason.TOOL_CALL_MISMATCH)
        return failures

    @staticmethod
    def check_arguments(
            actual_tool_call: ParsedToolCall,
            expected_arguments: Dict[str, Argument],
            ts: TestStats,
    ) -> List[Failure]:
        """
        Validates the arguments of a tool call against expected arguments.
        Adapted to use the ParsedToolCall structure.
        """
        failures = []
        arguments = actual_tool_call.args

        for field, expected_value in expected_arguments.items():
            actual_value = arguments.get(field)
            if actual_value is not None:
                # Convert actual value to string for consistent comparison
                failure = expected_value.check(str(actual_value))
                if failure:
                    failures.extend(failure)
                    ts.increment_failure(FailureReason.ARGUMENTS)
            else:
                failures.append(
                    Failure(None, expected_value, f"Argument '{field}' missing in response")
                )
        return failures

    @staticmethod
    def check_attachments(
        attachments: List[Any], expected_attachments: List[AttachmentCheck], ts: TestStats
    ) -> List[Failure]:
        """
        Validates attachments against expected attachments.

        Args:
            attachments (List[Attachment]): Actual attachments.
            expected_attachments (List[AttachmentCheck]): Expected attachments.
            ts (TestStats): Test statistics.

        Returns:
            List[Failure]: List of failures if attachments do not match.
        """
        failures = []
        if attachments is None:
            attachments = []
        if not expected_attachments:
            return failures

        for expected_attachment in expected_attachments:
            found = False
            for actual_attachment in attachments:
                if ResponseValidator._matches_attachment(actual_attachment, expected_attachment):
                    found = True
                    break

            if not found:
                if expected_attachment.title_soft and expected_attachment.title_soft[
                    0
                ].title().startswith("["):
                    ts.increment_failure(FailureReason.CITATION)
                else:
                    ts.increment_failure(FailureReason.ATTACHMENT)
                failures.append(
                    Failure(
                        [attachment.__dict__ for attachment in attachments],
                        expected_attachment.__dict__,
                        "Expected attachment not found in actual attachments",
                    )
                )

        return failures

    @staticmethod
    def _matches_attachment(actual: Any, expected: AttachmentCheck) -> bool:
        """
        Checks if an actual attachment matches an expected attachment.

        Args:
            actual (Attachment): Actual attachment.
            expected (AttachmentCheck): Expected attachment.

        Returns:
            bool: True if the attachments match, False otherwise.
        """
        # Type check
        if expected.type and actual.type != expected.type:
            return False

        # Strict title check
        if expected.title_strict and expected.title_strict not in actual.title:
            return False

        # Soft title check
        if expected.title_soft:
            similarity, max_similarity_alternative = get_similarity_alternatives(
                actual.title, expected.title_soft
            )
            if similarity < expected.similarity_threshold:
                return False

        return True
