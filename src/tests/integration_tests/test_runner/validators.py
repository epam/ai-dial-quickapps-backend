import json
import logging
from typing import Any, NamedTuple

from aidial_sdk.chat_completion.request import Message, Role

from quickapp.agent.models import TOOL_EXECUTION_HISTORY
from tests.integration_tests.conftest import FailureReason, TestStats
from tests.integration_tests.test_runner.models import Argument, AttachmentCheck, Failure, ToolCall
from tests.integration_tests.test_runner.similarity_checker import (
    get_similarity,
    get_similarity_alternatives,
)
from tests.integration_tests.test_runner.utils.string_utils import truncate_string

logger = logging.getLogger(__name__)


class ParsedToolCall(NamedTuple):
    """A simple data structure to hold the essential information from a tool call."""

    name: str
    args: dict[str, Any]
    result: str

    _LOG_RESULT_MAX_LEN = 50

    def __str__(self) -> str:
        result_preview = truncate_string(self.result, self._LOG_RESULT_MAX_LEN)
        return f"ParsedToolCall(name={self.name!r}, args={self.args!r}, result={result_preview!r})"


class ResponseValidator:
    """
    Validates responses against expected tool calls, arguments, and attachments.
    """

    @staticmethod
    def validate_json_schema_response(
        content: str, response_format: dict[str, Any], ts: TestStats
    ) -> list[Failure]:
        """
        Validates that the response content is valid JSON and optionally matches a schema.

        Args:
            content (str): The response content to validate
            response_format (dict): The response format specification with type and optional json_schema
            ts (TestStats): Test statistics tracker

        Returns:
            list[Failure]: List of validation failures
        """
        logger.debug(
            "validate_json_schema_response called with response_format: %s", response_format
        )
        failures = []

        if not content or not content.strip():
            logger.warning("Response content is empty or only whitespace")
            ts.increment_failure(FailureReason.ANSWER)
            failures.append(
                Failure(
                    actual=content, expected="non-empty JSON", comment="Response content is empty"
                )
            )
            return failures

        # Check if response is valid JSON
        try:
            parsed_json = json.loads(content)
            logger.debug("Response content parsed as JSON successfully")
        except json.JSONDecodeError as e:
            logger.warning("Response is not valid JSON: %s", e)
            ts.increment_failure(FailureReason.ANSWER)
            failures.append(
                Failure(
                    actual=content,
                    expected="valid JSON",
                    comment=f"Response is not valid JSON: {str(e)}",
                )
            )
            return failures

        # If json_schema is provided, validate against it
        if response_format.get("type") == "json_schema" and "json_schema" in response_format:
            schema = response_format["json_schema"].get("schema", {})
            if schema:
                logger.debug("Starting JSON schema validation; schema: %s", schema)
                before_count = len(failures)
                failures.extend(ResponseValidator._validate_against_schema(parsed_json, schema, ts))
                after_count = len(failures)
                if after_count == before_count:
                    logger.info("JSON schema validation passed")
                else:
                    logger.warning(
                        "JSON schema validation failed with %d new failure(s)",
                        after_count - before_count,
                    )
            else:
                logger.debug(
                    "json_schema provided but no 'schema' found; skipping schema validation"
                )
        else:
            logger.debug("No json_schema validation requested; JSON parsing succeeded")

        return failures

    @staticmethod
    def _validate_against_schema(
        data: Any, schema: dict[str, Any], ts: TestStats, path: str = "root"
    ) -> list[Failure]:
        """
        Validates data against a JSON schema (basic validation).

        Args:
            data: The parsed JSON data
            schema: The JSON schema to validate against
            ts: Test statistics tracker
            path: Current path in the data structure (for error messages)

        Returns:
            list[Failure]: List of validation failures
        """
        failures = []

        # Check type
        schema_type = schema.get("type")
        if schema_type:
            if not ResponseValidator._check_type(data, schema_type):
                ts.increment_failure(FailureReason.ANSWER)
                failures.append(
                    Failure(
                        actual=type(data).__name__,
                        expected=schema_type,
                        comment=f"Type mismatch at {path}: expected {schema_type}",
                    )
                )
                return failures

        # Check required properties for objects
        if schema_type == "object" and isinstance(data, dict):
            required = schema.get("required", [])
            for req_field in required:
                if req_field not in data:
                    ts.increment_failure(FailureReason.ANSWER)
                    failures.append(
                        Failure(
                            actual=list(data.keys()),
                            expected=req_field,
                            comment=f"Required field '{req_field}' missing at {path}",
                        )
                    )

            # Validate properties
            properties = schema.get("properties", {})
            for prop_name, prop_schema in properties.items():
                if prop_name in data:
                    failures.extend(
                        ResponseValidator._validate_against_schema(
                            data[prop_name], prop_schema, ts, f"{path}.{prop_name}"
                        )
                    )

        # Check array items
        if schema_type == "array" and isinstance(data, list):
            items_schema = schema.get("items", {})
            if items_schema:
                for idx, item in enumerate(data):
                    failures.extend(
                        ResponseValidator._validate_against_schema(
                            item, items_schema, ts, f"{path}[{idx}]"
                        )
                    )

        return failures

    @staticmethod
    def _check_type(data: Any, schema_type: str) -> bool:
        """Check if data matches the schema type."""
        type_mapping = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }

        expected_type = type_mapping.get(schema_type)
        if expected_type is None:
            return True

        return isinstance(data, expected_type)

    @staticmethod
    def _parse_intermediate_steps(state: dict) -> list[ParsedToolCall]:
        """Parse tool execution history from state.

        Expects message-based format: list of serialized Message objects.
        """
        if state is None:
            return []
        steps = state.get(TOOL_EXECUTION_HISTORY)
        if not steps:
            return []

        try:
            parsed_calls = []
            pending_results: dict[str, str] = {}

            # First pass: collect all TOOL results
            for step in steps:
                msg = Message(**step) if isinstance(step, dict) else step
                if msg.role == Role.TOOL and msg.tool_call_id:
                    pending_results[msg.tool_call_id] = str(msg.content) if msg.content else ""

            # Second pass: extract tool calls with their results
            for step in steps:
                msg = Message(**step) if isinstance(step, dict) else step
                if msg.role == Role.ASSISTANT and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_input = tc.function.arguments
                        if isinstance(tool_input, str):
                            try:
                                args = json.loads(tool_input)
                            except json.JSONDecodeError:
                                args = {"input": tool_input}
                        else:
                            args = tool_input or {}

                        parsed_calls.append(
                            ParsedToolCall(
                                name=tc.function.name,
                                args=args,
                                result=pending_results.get(tc.id, ""),
                            )
                        )

            return parsed_calls
        except (json.JSONDecodeError, TypeError, IndexError) as e:
            print(f"Error parsing intermediate_steps: {e}")
            return []

    @staticmethod
    def check_similarity(
        actual: str, expected: str, failure_message: str, similarity_threshold: float
    ) -> list[Failure]:
        """
        Checks if the similarity between actual and expected text meets the threshold.

        Args:
            actual (str): Actual text.
            expected (str): Expected text.
            failure_message (str): Message for failure.
            similarity_threshold (float): Minimum similarity required.

        Returns:
            list[Failure]: List of failures if similarity is below threshold.
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

    @staticmethod
    def check_tool_calls(
        state: dict, expected_tool_calls: list[ToolCall], ts: TestStats
    ) -> list[Failure]:
        """
        Validates tool calls in the response against expected calls.
        """
        failures = []
        tool_call_history = ResponseValidator._parse_intermediate_steps(state)

        # Filter out failed py_code_interpreter calls
        tool_call_history = ResponseValidator._filter_py_code_interpreter(tool_call_history)

        # Validate tool call counts
        failures.extend(
            ResponseValidator._validate_tool_call_counts(tool_call_history, expected_tool_calls, ts)
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
        tool_call_history: list[ParsedToolCall],
    ) -> list[ParsedToolCall]:
        """
        Filters out failed internal_code_execution_python_interpreter tool calls.
        Adapted to use the ParsedToolCall structure.
        """
        return [
            tool_call
            for tool_call in tool_call_history
            if not (
                tool_call.name == 'internal_code_execution_python_interpreter'
                and (
                    "FAILURE" in tool_call.result
                    or "Python Code Interpreter session has been closed" in tool_call.result
                )
            )
        ]

    @staticmethod
    def _validate_tool_call_counts(
        tool_call_history: list[ParsedToolCall],
        expected_tool_calls: list[ToolCall],
        ts: TestStats,
    ) -> list[Failure]:
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
                        actual=call_count,
                        expected=f"{expected.min_calls}-{expected.max_calls}",
                        comment=f"'{expected.name}' called {call_count} times (min {expected.min_calls} required)",
                    )
                )
                ts.increment_failure(FailureReason.TOOL_CALL_COUNT)
            if call_count > expected.max_calls:
                failures.append(
                    Failure(
                        actual=call_count,
                        expected=f"{expected.min_calls}-{expected.max_calls}",
                        comment=f"'{expected.name}' called {call_count} times (max {expected.max_calls} allowed)",
                    )
                )
                ts.increment_failure(FailureReason.TOOL_CALL_COUNT)
        return failures

    @staticmethod
    def _validate_tool_call_arguments(
        tool_call_history: list[ParsedToolCall],
        expected_tool_calls: list[ToolCall],
        ts: TestStats,
    ) -> list[Failure]:
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
                        actual=[str(call) for call in tool_call_history],
                        expected=expected.arguments,
                        comment=f"No matching call for '{expected.name}' found with the required arguments.",
                    )
                )
                ts.increment_failure(FailureReason.ARGUMENTS)
        return failures

    @staticmethod
    def _check_unexpected_tools(
        tool_call_history: list[ParsedToolCall],
        expected_tool_calls: list[ToolCall],
        ts: TestStats,
    ) -> list[Failure]:
        """
        Checks for unexpected tool calls.
        """
        failures = []
        expected_names = {tc.name for tc in expected_tool_calls}
        expected_names.add("internal_skills_read_skill")
        expected_names.add("internal_attachments_get_content")
        for actual in tool_call_history:
            if actual.name not in expected_names:
                failures.append(
                    Failure(
                        actual=actual.name,
                        expected="No unexpected tools",
                        comment=f"Unexpected tool '{actual.name}' called",
                    )
                )
                ts.increment_failure(FailureReason.TOOL_CALL_MISMATCH)
        return failures

    @staticmethod
    def check_arguments(
        actual_tool_call: ParsedToolCall,
        expected_arguments: dict[str, Argument],
        ts: TestStats,
    ) -> list[Failure]:
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
                    Failure(
                        actual=None,
                        expected=expected_value,
                        comment=f"Argument '{field}' missing in response",
                    )
                )
        return failures

    @staticmethod
    def check_attachments(
        attachments: list[Any], expected_attachments: list[AttachmentCheck], ts: TestStats
    ) -> list[Failure]:
        """
        Validates attachments against expected attachments.

        Args:
            attachments (list[Attachment]): Actual attachments.
            expected_attachments (list[AttachmentCheck]): Expected attachments.
            ts (TestStats): Test statistics.

        Returns:
            list[Failure]: List of failures if attachments do not match.
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
                        actual=[attachment.__dict__ for attachment in attachments],
                        expected=expected_attachment.__dict__,
                        comment="Expected attachment not found in actual attachments",
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
